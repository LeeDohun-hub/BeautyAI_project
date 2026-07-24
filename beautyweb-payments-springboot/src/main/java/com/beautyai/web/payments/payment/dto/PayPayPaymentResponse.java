package com.beautyai.web.payments.payment.dto;

import com.beautyai.web.payments.payment.Payment;
import com.beautyai.web.payments.payment.PaymentStatus;
import java.time.OffsetDateTime;

public record PayPayPaymentResponse(
    String paymentId,
    String orderId,
    String merchantPaymentId,
    String provider,
    PaymentStatus status,
    Integer amount,
    String currency,
    String paypayCodeId,
    String paymentUrl,
    String deeplink,
    OffsetDateTime expiresAt,
    Integer pollAfterSeconds
) {
    public static PayPayPaymentResponse from(Payment payment) {
        return new PayPayPaymentResponse(
            payment.getPaymentId(),
            payment.getOrderId(),
            payment.getMerchantPaymentId(),
            payment.getProvider(),
            payment.getStatus(),
            payment.getAmount(),
            payment.getCurrency(),
            payment.getPaypayCodeId(),
            payment.getPaymentUrl(),
            payment.getDeeplink(),
            payment.getExpiresAt(),
            3
        );
    }
}
