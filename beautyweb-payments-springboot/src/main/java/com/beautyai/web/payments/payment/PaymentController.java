package com.beautyai.web.payments.payment;

import com.beautyai.web.payments.payment.dto.CreatePayPayPaymentRequest;
import com.beautyai.web.payments.payment.dto.PayPayPaymentResponse;
import com.beautyai.web.payments.payment.dto.PayPayStatusResponse;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/web/payments/paypay")
public class PaymentController {
    private final PaymentService paymentService;

    public PaymentController(PaymentService paymentService) {
        this.paymentService = paymentService;
    }

    @PostMapping
    public PayPayPaymentResponse create(@Valid @RequestBody CreatePayPayPaymentRequest request) {
        return paymentService.createPayPayPayment(request);
    }

    @GetMapping("/{paymentId}")
    public PayPayStatusResponse status(@PathVariable String paymentId) {
        return paymentService.getPayPayPaymentStatus(paymentId);
    }
}
