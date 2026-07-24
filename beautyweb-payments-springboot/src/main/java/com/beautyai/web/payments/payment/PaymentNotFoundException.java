package com.beautyai.web.payments.payment;

public class PaymentNotFoundException extends RuntimeException {
    public PaymentNotFoundException(String paymentId) {
        super("Payment not found: " + paymentId);
    }
}
