package com.beautyai.web.payments.payment.dto;

import com.beautyai.web.payments.payment.Payment;
import com.beautyai.web.payments.payment.PaymentStatus;
import java.time.OffsetDateTime;

public record PayPayStatusResponse(
    String paymentId,
    String orderId,
    String merchantPaymentId,
    String provider,
    PaymentStatus status,
    String providerStatus,
    String paypayPaymentId,
    Integer amount,
    String currency,
    OffsetDateTime paidAt,
    OffsetDateTime lastSyncedAt
) {
    public static PayPayStatusResponse from(Payment payment) {
        return new PayPayStatusResponse(
            payment.getPaymentId(),
            payment.getOrderId(),
            payment.getMerchantPaymentId(),
            payment.getProvider(),
            payment.getStatus(),
            payment.getProviderStatus(),
            payment.getPaypayPaymentId(),
            payment.getAmount(),
            payment.getCurrency(),
            payment.getPaidAt(),
            payment.getLastSyncedAt()
        );
    }
}
