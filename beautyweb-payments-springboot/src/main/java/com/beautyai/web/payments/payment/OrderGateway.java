package com.beautyai.web.payments.payment;

public interface OrderGateway {
    void assertPayable(String orderId, int amount, String currency);
    void markPaid(String orderId, String paymentId);
}
