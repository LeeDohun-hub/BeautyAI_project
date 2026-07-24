package com.beautyai.web.payments.payment;

import org.springframework.stereotype.Component;

@Component
public class NoopOrderGateway implements OrderGateway {
    @Override
    public void assertPayable(String orderId, int amount, String currency) {
        // Replace this with BeautyWEB order lookup before production.
    }

    @Override
    public void markPaid(String orderId, String paymentId) {
        // Replace this with BeautyWEB order status update before production.
    }
}
