package com.beautyai.web.payments.payment.dto;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

public record CreatePayPayPaymentRequest(
    @NotBlank String orderId,
    @NotNull @Min(1) Integer amount,
    @NotBlank String currency,
    String returnUrl,
    String userIp
) {
}
