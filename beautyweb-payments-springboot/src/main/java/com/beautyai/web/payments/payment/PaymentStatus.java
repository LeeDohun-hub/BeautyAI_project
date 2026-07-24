package com.beautyai.web.payments.payment;

public enum PaymentStatus {
    CREATING(false),
    CREATED(false),
    AUTHORIZED(false),
    COMPLETED(true),
    FAILED(true),
    CANCELED(true),
    EXPIRED(true),
    REFUNDED(true),
    UNKNOWN(false);

    private final boolean terminal;

    PaymentStatus(boolean terminal) {
        this.terminal = terminal;
    }

    public boolean isTerminal() {
        return terminal;
    }

    public static PaymentStatus fromPayPayStatus(String status) {
        if (status == null || status.isBlank()) {
            return UNKNOWN;
        }
        try {
            return PaymentStatus.valueOf(status);
        } catch (IllegalArgumentException ignored) {
            return UNKNOWN;
        }
    }
}
