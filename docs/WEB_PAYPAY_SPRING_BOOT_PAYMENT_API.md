# WEB PayPay Spring Boot Payment API Design

## 1. Scope

BeautyWEB에서 PayPay 실제 결제를 붙이기 위한 Spring Boot 백엔드 API 설계다. 1차 범위는 다음 2개 API로 제한한다.

- 결제 생성: BeautyWEB 주문을 PayPay Dynamic QR Code로 전환하고 `url`/`deeplink`를 반환한다.
- 결제 상태조회: 프론트가 PayPay 결제 완료 여부를 폴링하거나 주문 상세에서 최신 상태를 확인한다.

환불, 취소, webhook은 운영 안정화를 위해 후속 범위로 두되, 테이블과 상태 모델은 확장 가능하게 잡는다.

## 2. PayPay Official API Mapping

PayPay OPA Dynamic QR Code 흐름을 사용한다.

| BeautyWEB use case | PayPay API | Method | Path |
|---|---|---|---|
| 결제 생성 | Create a QRCode | `POST` | `/v2/codes` |
| 결제 상태조회 | Get payment details | `GET` | `/v2/codes/payments/{merchantPaymentId}` |

PayPay 공식 문서 기준 주요 제약:

- `merchantPaymentId`는 가맹점이 생성하는 유니크 거래 ID이며 64자 이하로 관리한다.
- 결제 생성 응답에는 `url`, `deeplink`, `expiryDate`, `merchantPaymentId`가 포함된다.
- 상태조회 응답의 `data.status`는 `CREATED`, `COMPLETED`, `FAILED`, `CANCELED`, `EXPIRED`, `REFUNDED` 등 주문 상태 판단의 기준으로 사용한다.
- 결제 생성 API read timeout은 최소 30초로 잡고, timeout이면 우리 DB 상태를 `UNKNOWN`으로 두고 상태조회로 복구한다.
- Dynamic QR Code polling은 공식 문서에서 약 2-3초 간격을 안내한다. 프론트 과호출 방지를 위해 BeautyWEB API는 3초 이상의 클라이언트 폴링을 권장한다.

## 3. Runtime Configuration

```yaml
paypay:
  environment: sandbox # sandbox | staging | production
  api-key: ${PAYPAY_API_KEY}
  api-secret: ${PAYPAY_API_SECRET}
  merchant-id: ${PAYPAY_MERCHANT_ID}
  store-id: ${PAYPAY_STORE_ID:beautyai-web}
  terminal-id: ${PAYPAY_TERMINAL_ID:web}
  base-url:
    sandbox: https://apigw.sandbox.paypay.ne.jp
    staging: https://apigw.stg.paypay.ne.jp
    production: https://apigw.paypay.ne.jp
  order-description-prefix: BeautyAI
```

Secrets must stay server-side only. The frontend receives only BeautyWEB payment IDs, PayPay redirect/deeplink URLs, and normalized status.

## 4. BeautyWEB API Contract

### 4.1 Create PayPay Payment

`POST /api/web/payments/paypay`

Request:

```json
{
  "orderId": "ord_20260723_000001",
  "amount": 3980,
  "currency": "JPY",
  "returnUrl": "https://beauty.example.com/orders/ord_20260723_000001",
  "userIp": "203.0.113.10"
}
```

Response:

```json
{
  "paymentId": "pay_20260723_000001",
  "orderId": "ord_20260723_000001",
  "merchantPaymentId": "BAI-20260723-000001",
  "provider": "PAYPAY",
  "status": "CREATED",
  "amount": 3980,
  "currency": "JPY",
  "paypayCodeId": "04-xxxxxxxx",
  "paymentUrl": "https://qr.paypay.ne.jp/...",
  "deeplink": "paypay://payment?link_key=...",
  "expiresAt": "2026-07-23T07:15:00Z",
  "pollAfterSeconds": 3
}
```

Validation:

- `amount`는 JPY 정수 금액으로 1 이상.
- `currency`는 1차 릴리스에서 `JPY`만 허용.
- `orderId`는 BeautyWEB 주문 테이블에 존재하고 결제 가능 상태여야 한다.
- 동일 주문에 `CREATED`/`UNKNOWN` 결제가 있으면 새 PayPay QR을 만들지 않고 기존 결제 정보를 반환한다.

### 4.2 Get PayPay Payment Status

`GET /api/web/payments/paypay/{paymentId}`

Response:

```json
{
  "paymentId": "pay_20260723_000001",
  "orderId": "ord_20260723_000001",
  "merchantPaymentId": "BAI-20260723-000001",
  "provider": "PAYPAY",
  "status": "COMPLETED",
  "providerStatus": "COMPLETED",
  "paypayPaymentId": "PAYPAY_PAYMENT_ID",
  "amount": 3980,
  "currency": "JPY",
  "paidAt": "2026-07-23T07:12:11Z",
  "lastSyncedAt": "2026-07-23T07:12:13Z"
}
```

Behavior:

- 내부 DB 상태가 terminal status라면 PayPay를 재조회하지 않고 반환한다.
- `CREATED`/`UNKNOWN` 상태면 PayPay 상태조회 API를 호출하고 DB를 갱신한다.
- PayPay `COMPLETED` 수신 시 주문 상태를 `PAID`로 전환한다.
- PayPay 404가 오면 QR 만료 또는 결제 미발생 가능성이 있으므로 우리 상태는 즉시 실패 처리하지 않고 `CREATED` 또는 `UNKNOWN`을 유지한다. 만료 시간이 지났으면 `EXPIRED`로 전환한다.

## 5. Status Mapping

| PayPay status | BeautyWEB payment status | Order action |
|---|---|---|
| `CREATED` | `CREATED` | 주문 `PAYMENT_PENDING` 유지 |
| `COMPLETED` | `COMPLETED` | 주문 `PAID` 전환, 재고/루틴세트 확정 |
| `AUTHORIZED` | `AUTHORIZED` | 1차에서는 미사용, pre-auth 도입 시 처리 |
| `FAILED` | `FAILED` | 주문 `PAYMENT_FAILED` 또는 재시도 가능 |
| `CANCELED` | `CANCELED` | 주문 `PAYMENT_CANCELED` |
| `EXPIRED` | `EXPIRED` | 주문 `PAYMENT_EXPIRED` |
| `REFUNDED` | `REFUNDED` | 주문 `REFUNDED` |
| timeout/network error | `UNKNOWN` | 상태조회 재시도 |

Terminal statuses: `COMPLETED`, `FAILED`, `CANCELED`, `EXPIRED`, `REFUNDED`.

## 6. Database Design

```sql
create table payments (
  id bigint primary key generated always as identity,
  payment_id varchar(40) not null unique,
  order_id varchar(40) not null,
  provider varchar(20) not null,
  status varchar(30) not null,
  provider_status varchar(30),
  merchant_payment_id varchar(64) not null unique,
  amount integer not null,
  currency char(3) not null,
  paypay_code_id varchar(100),
  paypay_payment_id varchar(100),
  payment_url varchar(1000),
  deeplink varchar(1000),
  expires_at timestamp with time zone,
  paid_at timestamp with time zone,
  last_synced_at timestamp with time zone,
  raw_create_response jsonb,
  raw_status_response jsonb,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now()
);

create index idx_payments_order_provider on payments(order_id, provider);
create index idx_payments_status on payments(status);
```

`merchant_payment_id` generation rule:

```text
BAI-{yyyyMMdd}-{orderNumericOrShortUuid}
```

Allowed characters should stay within `A-Z`, `a-z`, `0-9`, `-`, `_`, and total length must be 64 or less.

## 7. Spring Boot Package Layout

```text
com.beautyai.web.payment
  PaymentController.java
  PaymentService.java
  PaymentRepository.java
  Payment.java
  PaymentStatus.java
  PayPayClient.java
  PayPayProperties.java
  PayPayHmacSigner.java
  dto/
    CreatePayPayPaymentRequest.java
    PayPayPaymentResponse.java
    PayPayStatusResponse.java
    PayPayCreateCodeRequest.java
    PayPayCreateCodeResponse.java
    PayPayPaymentDetailsResponse.java
```

## 8. Controller Sketch

```java
@RestController
@RequestMapping("/api/web/payments/paypay")
@RequiredArgsConstructor
public class PaymentController {
    private final PaymentService paymentService;

    @PostMapping
    public PayPayPaymentResponse create(@Valid @RequestBody CreatePayPayPaymentRequest request) {
        return paymentService.createPayPayPayment(request);
    }

    @GetMapping("/{paymentId}")
    public PayPayStatusResponse status(@PathVariable String paymentId) {
        return paymentService.getPayPayPaymentStatus(paymentId);
    }
}
```

## 9. Service Flow

Create:

1. Load BeautyWEB order and verify payable state.
2. Find reusable non-terminal PayPay payment for the same order.
3. Generate `merchantPaymentId`.
4. Insert local payment row as `CREATING`.
5. Call PayPay `POST /v2/codes` with:
   - `merchantPaymentId`
   - `amount.amount`
   - `amount.currency = JPY`
   - `codeType = ORDER_QR`
   - `orderDescription`
   - `storeId`
   - `terminalId`
   - `requestedAt`
   - `ipAddress` if available
6. Save `codeId`, `url`, `deeplink`, `expiryDate`, raw response.
7. Return normalized payment response.

Status:

1. Load local payment by `paymentId`.
2. If terminal, return local state.
3. Call PayPay `GET /v2/codes/payments/{merchantPaymentId}`.
4. Map `data.status` and update local row.
5. If `COMPLETED`, update order payment state transactionally.
6. Return normalized status response.

## 10. PayPay HMAC Signing

PayPay OPA uses HMAC authentication in the `Authorization` header. Implement signing in one isolated class.

Signing inputs:

- API key
- API secret
- request URI only, for example `/v2/codes`
- HTTP method
- nonce
- epoch seconds
- content type
- MD5 hash of content type + request body, or `empty` for GET/no body

Header shape:

```text
hmac OPA-Auth:{apiKey}:{macData}:{nonce}:{epoch}:{hash}
```

Spring implementation notes:

- Use `WebClient`.
- Serialize JSON body once, then sign exactly that serialized string.
- Set `Content-Type: application/json;charset=UTF-8` consistently between signing and request.
- For agent merchant mode, pass `X-ASSUME-MERCHANT: {merchantId}`.
- Log PayPay `X-REQUEST-ID` on every response/error for support tracing.

## 11. Error Handling

| Condition | API response to frontend | Internal action |
|---|---|---|
| PayPay 401 | `502 BAD_GATEWAY` | alert config/secret issue |
| PayPay 400 duplicate | return existing payment if same `merchantPaymentId` | idempotency recovery |
| Create timeout | `202 ACCEPTED` with `UNKNOWN` | allow status polling |
| Status timeout | latest local status | keep `UNKNOWN` or previous status |
| PayPay 5xx | `502 BAD_GATEWAY` | retry with backoff on next status request |
| Local order not payable | `409 CONFLICT` | no PayPay call |

Do not expose PayPay API key, signature, full raw errors, or stack traces to the frontend.

## 12. Frontend Flow

1. User selects PayPay and clicks pay.
2. Frontend calls `POST /api/web/payments/paypay`.
3. Mobile: open `deeplink` first, fallback to `paymentUrl`.
4. Desktop: render QR from `paymentUrl` or open PayPay web screen depending UX choice.
5. Frontend polls `GET /api/web/payments/paypay/{paymentId}` every 3 seconds.
6. On `COMPLETED`, route to order complete page.
7. On `EXPIRED`/`FAILED`/`CANCELED`, show retry option that creates a new payment.

## 13. Test Plan

Unit tests:

- `PayPayHmacSigner` produces stable header shape for POST and GET.
- `PaymentService` reuses existing pending payment.
- Status mapping covers all known PayPay statuses.
- Timeout maps to `UNKNOWN`.

Integration tests with mocked PayPay:

- create success stores `url`, `deeplink`, `expiryDate`.
- status `COMPLETED` updates payment and order exactly once.
- duplicate create request is idempotent.
- PayPay 404 before expiry does not incorrectly fail the order.

Manual sandbox test:

1. Configure sandbox `PAYPAY_API_KEY`, `PAYPAY_API_SECRET`, `PAYPAY_MERCHANT_ID`.
2. Create an order with JPY amount.
3. Call BeautyWEB create API.
4. Open returned PayPay URL/deeplink.
5. Poll status until `COMPLETED`.
6. Confirm order changed to `PAID`.

## 14. Open Decisions

- Whether BeautyWEB will render QR directly or redirect to PayPay URL.
- Whether webhook is required for MVP. Recommended: add webhook before production launch to avoid relying only on polling.
- Whether PayPay cancellation API should be exposed for abandoned checkout cleanup.
- Whether payment records live in BeautyWEB DB only or are synchronized back to BeautyAI recommendation history.

## 15. References

- PayPay Dynamic QR Code API: https://www.paypay.ne.jp/opa/doc/v1.0/dynamicqrcode
- PayPay OPA API Authorization: https://www.paypay.ne.jp/opa/doc/v1.0/api_authorization.html
- PayPay Java SDK: https://github.com/paypay/paypayopa-sdk-java
