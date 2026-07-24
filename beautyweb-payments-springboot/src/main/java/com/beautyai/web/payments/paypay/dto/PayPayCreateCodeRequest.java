package com.beautyai.web.payments.paypay.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record PayPayCreateCodeRequest(
    String merchantPaymentId,
    MoneyAmount amount,
    String codeType,
    String orderDescription,
    String storeId,
    String terminalId,
    Long requestedAt,
    Boolean isAuthorization,
    String redirectUrl,
    String redirectType,
    String ipAddress
) {
}
