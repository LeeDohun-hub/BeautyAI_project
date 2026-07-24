package com.beautyai.web.payments.payment;

import com.beautyai.web.payments.payment.dto.CreatePayPayPaymentRequest;
import com.beautyai.web.payments.payment.dto.PayPayPaymentResponse;
import com.beautyai.web.payments.payment.dto.PayPayStatusResponse;
import com.beautyai.web.payments.paypay.PayPayApiException;
import com.beautyai.web.payments.paypay.PayPayClient;
import com.beautyai.web.payments.paypay.PayPayProperties;
import com.beautyai.web.payments.paypay.dto.MoneyAmount;
import com.beautyai.web.payments.paypay.dto.PayPayCreateCodeRequest;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.Locale;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PaymentService {
    private static final String PROVIDER_PAYPAY = "PAYPAY";
    private static final String ORDER_QR = "ORDER_QR";

    private final PaymentRepository paymentRepository;
    private final PayPayClient payPayClient;
    private final PayPayProperties payPayProperties;
    private final ObjectMapper objectMapper;
    private final OrderGateway orderGateway;

    public PaymentService(
        PaymentRepository paymentRepository,
        PayPayClient payPayClient,
        PayPayProperties payPayProperties,
        ObjectMapper objectMapper,
        OrderGateway orderGateway
    ) {
        this.paymentRepository = paymentRepository;
        this.payPayClient = payPayClient;
        this.payPayProperties = payPayProperties;
        this.objectMapper = objectMapper;
        this.orderGateway = orderGateway;
    }

    @Transactional
    public PayPayPaymentResponse createPayPayPayment(CreatePayPayPaymentRequest request) {
        String currency = request.currency().toUpperCase(Locale.ROOT);
        if (!"JPY".equals(currency)) {
            throw new IllegalArgumentException("PayPay MVP supports JPY only");
        }
        orderGateway.assertPayable(request.orderId(), request.amount(), currency);

        Payment reusable = findReusablePendingPayment(request.orderId());
        if (reusable != null) {
            return PayPayPaymentResponse.from(reusable);
        }

        Payment payment = new Payment();
        payment.setPaymentId(newPaymentId());
        payment.setOrderId(request.orderId());
        payment.setProvider(PROVIDER_PAYPAY);
        payment.setStatus(PaymentStatus.CREATING);
        payment.setMerchantPaymentId(newMerchantPaymentId(request.orderId()));
        payment.setAmount(request.amount());
        payment.setCurrency(currency);
        payment = paymentRepository.saveAndFlush(payment);

        PayPayCreateCodeRequest payPayRequest = new PayPayCreateCodeRequest(
            payment.getMerchantPaymentId(),
            new MoneyAmount(payment.getAmount(), payment.getCurrency()),
            ORDER_QR,
            orderDescription(payment.getOrderId()),
            payPayProperties.getStoreId(),
            payPayProperties.getTerminalId(),
            Instant.now().getEpochSecond(),
            false,
            request.returnUrl(),
            request.returnUrl() == null || request.returnUrl().isBlank() ? null : "WEB_LINK",
            request.userIp()
        );

        try {
            JsonNode response = payPayClient.createCode(payPayRequest);
            applyCreateResponse(payment, response);
        } catch (PayPayApiException e) {
            payment.setStatus(PaymentStatus.UNKNOWN);
            payment.setRawCreateResponse(e.getResponseBody());
            if (e.getStatusCode() == 401 || e.getStatusCode() == 400) {
                throw e;
            }
            return PayPayPaymentResponse.from(paymentRepository.save(payment));
        } catch (IllegalStateException e) {
            throw e;
        } catch (RuntimeException e) {
            payment.setStatus(PaymentStatus.UNKNOWN);
            return PayPayPaymentResponse.from(paymentRepository.save(payment));
        }
        return PayPayPaymentResponse.from(paymentRepository.save(payment));
    }

    @Transactional
    public PayPayStatusResponse getPayPayPaymentStatus(String paymentId) {
        Payment payment = paymentRepository.findByPaymentId(paymentId)
            .orElseThrow(() -> new PaymentNotFoundException(paymentId));

        if (payment.getStatus().isTerminal()) {
            return PayPayStatusResponse.from(payment);
        }

        try {
            JsonNode response = payPayClient.getPaymentDetails(payment.getMerchantPaymentId());
            applyStatusResponse(payment, response);
        } catch (PayPayApiException e) {
            if (isExpired(payment)) {
                payment.setStatus(PaymentStatus.EXPIRED);
                payment.setProviderStatus("EXPIRED");
            } else if (payment.getStatus() == PaymentStatus.CREATING) {
                payment.setStatus(PaymentStatus.UNKNOWN);
            }
            payment.setRawStatusResponse(e.getResponseBody());
        } catch (RuntimeException e) {
            if (payment.getStatus() == PaymentStatus.CREATING) {
                payment.setStatus(PaymentStatus.UNKNOWN);
            }
        }

        Payment saved = paymentRepository.save(payment);
        if (saved.getStatus() == PaymentStatus.COMPLETED) {
            orderGateway.markPaid(saved.getOrderId(), saved.getPaymentId());
        }
        return PayPayStatusResponse.from(saved);
    }

    private Payment findReusablePendingPayment(String orderId) {
        return paymentRepository.findByOrderIdAndProviderOrderByCreatedAtDesc(orderId, PROVIDER_PAYPAY)
            .stream()
            .filter(payment -> !payment.getStatus().isTerminal())
            .findFirst()
            .orElse(null);
    }

    private void applyCreateResponse(Payment payment, JsonNode response) {
        JsonNode data = response.path("data");
        payment.setStatus(PaymentStatus.CREATED);
        payment.setProviderStatus("CREATED");
        payment.setPaypayCodeId(text(data, "codeId"));
        payment.setPaymentUrl(text(data, "url"));
        payment.setDeeplink(text(data, "deeplink"));
        payment.setExpiresAt(epochToOffsetDateTime(data.path("expiryDate")));
        payment.setRawCreateResponse(toJson(response));
    }

    private void applyStatusResponse(Payment payment, JsonNode response) {
        JsonNode data = response.path("data");
        String providerStatus = text(data, "status");
        PaymentStatus status = PaymentStatus.fromPayPayStatus(providerStatus);
        payment.setStatus(status);
        payment.setProviderStatus(providerStatus);
        payment.setPaypayPaymentId(firstText(data, "paymentId", "paypayPaymentId"));
        if (status == PaymentStatus.COMPLETED && payment.getPaidAt() == null) {
            payment.setPaidAt(epochToOffsetDateTime(firstLong(data, "acceptedAt", "paidAt", "completedAt")));
        }
        payment.setLastSyncedAt(OffsetDateTime.now(ZoneOffset.UTC));
        payment.setRawStatusResponse(toJson(response));
    }

    private OffsetDateTime epochToOffsetDateTime(JsonNode node) {
        if (node == null || !node.canConvertToLong()) {
            return null;
        }
        return epochToOffsetDateTime(node.asLong());
    }

    private OffsetDateTime epochToOffsetDateTime(Long epochSeconds) {
        if (epochSeconds == null || epochSeconds <= 0) {
            return null;
        }
        return OffsetDateTime.ofInstant(Instant.ofEpochSecond(epochSeconds), ZoneOffset.UTC);
    }

    private boolean isExpired(Payment payment) {
        return payment.getExpiresAt() != null && payment.getExpiresAt().isBefore(OffsetDateTime.now(ZoneOffset.UTC));
    }

    private String orderDescription(String orderId) {
        return "%s order %s".formatted(payPayProperties.getOrderDescriptionPrefix(), orderId);
    }

    private String newPaymentId() {
        return "pay_" + UUID.randomUUID().toString().replace("-", "").substring(0, 24);
    }

    private String newMerchantPaymentId(String orderId) {
        String normalized = orderId.replaceAll("[^A-Za-z0-9_-]", "");
        if (normalized.length() > 32) {
            normalized = normalized.substring(normalized.length() - 32);
        }
        String suffix = UUID.randomUUID().toString().replace("-", "").substring(0, 8);
        return ("BAI-" + normalized + "-" + suffix).substring(0, Math.min(64, 13 + normalized.length()));
    }

    private String text(JsonNode node, String field) {
        JsonNode value = node.path(field);
        return value.isMissingNode() || value.isNull() ? null : value.asText();
    }

    private String firstText(JsonNode node, String... fields) {
        for (String field : fields) {
            String value = text(node, field);
            if (value != null && !value.isBlank()) {
                return value;
            }
        }
        return null;
    }

    private Long firstLong(JsonNode node, String... fields) {
        for (String field : fields) {
            JsonNode value = node.path(field);
            if (value.canConvertToLong()) {
                return value.asLong();
            }
        }
        return null;
    }

    private String toJson(JsonNode node) {
        try {
            return objectMapper.writeValueAsString(node);
        } catch (Exception e) {
            return node.toString();
        }
    }
}
