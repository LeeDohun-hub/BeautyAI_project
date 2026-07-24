# BeautyWEB Payments Spring Boot

PayPay Dynamic QR Code 결제 생성을 위한 Spring Boot 샘플 모듈입니다.

## Run

```powershell
$env:PAYPAY_API_KEY="your-api-key"
$env:PAYPAY_API_SECRET="your-api-secret"
$env:PAYPAY_MERCHANT_ID="your-merchant-id"
mvn spring-boot:run
```

Windows helper:

```powershell
copy .env.example .env
# Fill PAYPAY_API_KEY, PAYPAY_API_SECRET, PAYPAY_MERCHANT_ID.
.\run-paypay-backend.cmd
```

## APIs

- `POST /api/web/payments/paypay`
- `GET /api/web/payments/paypay/{paymentId}`
- `GET /api/web/postal-codes/{postalCode}`

Postal code example:

```http
GET /api/web/postal-codes/179-0073
```

```json
{
  "postalCode": "179-0073",
  "prefecture": "東京都",
  "city": "練馬区",
  "town": "田柄",
  "address": "東京都練馬区田柄"
}
```

## Notes

- 기본 DB는 H2 file DB(`./data/beautyweb-payments`)입니다.
- 운영에서는 `SPRING_DATASOURCE_URL`, `SPRING_DATASOURCE_USERNAME`, `SPRING_DATASOURCE_PASSWORD`를 PostgreSQL로 교체하세요.
- PayPay 서명은 `PayPayHmacSigner`가 공식 HMAC 절차대로 생성합니다.
- 현재 주문 검증/주문 상태 변경은 `OrderGateway` 인터페이스와 `NoopOrderGateway`로 분리해두었습니다. BeautyWEB 주문 모듈이 생기면 이 구현체만 교체하면 됩니다.
