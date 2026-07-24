package com.beautyai.web.payments.paypay;

public class PayPayApiException extends RuntimeException {
    private final int statusCode;
    private final String responseBody;

    public PayPayApiException(int statusCode, String responseBody) {
        super("PayPay API failed with status " + statusCode);
        this.statusCode = statusCode;
        this.responseBody = responseBody;
    }

    public int getStatusCode() {
        return statusCode;
    }

    public String getResponseBody() {
        return responseBody;
    }
}
