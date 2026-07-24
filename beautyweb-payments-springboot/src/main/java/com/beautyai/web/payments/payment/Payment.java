package com.beautyai.web.payments.payment;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import jakarta.persistence.Table;
import java.time.OffsetDateTime;

@Entity
@Table(
    name = "payments",
    indexes = {
        @Index(name = "idx_payments_order_provider", columnList = "order_id,provider"),
        @Index(name = "idx_payments_status", columnList = "status")
    }
)
public class Payment {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "payment_id", nullable = false, unique = true, length = 40)
    private String paymentId;

    @Column(name = "order_id", nullable = false, length = 40)
    private String orderId;

    @Column(nullable = false, length = 20)
    private String provider;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 30)
    private PaymentStatus status;

    @Column(name = "provider_status", length = 30)
    private String providerStatus;

    @Column(name = "merchant_payment_id", nullable = false, unique = true, length = 64)
    private String merchantPaymentId;

    @Column(nullable = false)
    private Integer amount;

    @Column(nullable = false, length = 3)
    private String currency;

    @Column(name = "paypay_code_id", length = 100)
    private String paypayCodeId;

    @Column(name = "paypay_payment_id", length = 100)
    private String paypayPaymentId;

    @Column(name = "payment_url", length = 1000)
    private String paymentUrl;

    @Column(length = 1000)
    private String deeplink;

    @Column(name = "expires_at")
    private OffsetDateTime expiresAt;

    @Column(name = "paid_at")
    private OffsetDateTime paidAt;

    @Column(name = "last_synced_at")
    private OffsetDateTime lastSyncedAt;

    @Column(name = "raw_create_response", columnDefinition = "text")
    private String rawCreateResponse;

    @Column(name = "raw_status_response", columnDefinition = "text")
    private String rawStatusResponse;

    @Column(name = "created_at", nullable = false)
    private OffsetDateTime createdAt;

    @Column(name = "updated_at", nullable = false)
    private OffsetDateTime updatedAt;

    @PrePersist
    void prePersist() {
        OffsetDateTime now = OffsetDateTime.now();
        createdAt = now;
        updatedAt = now;
    }

    @PreUpdate
    void preUpdate() {
        updatedAt = OffsetDateTime.now();
    }

    public Long getId() { return id; }
    public String getPaymentId() { return paymentId; }
    public void setPaymentId(String paymentId) { this.paymentId = paymentId; }
    public String getOrderId() { return orderId; }
    public void setOrderId(String orderId) { this.orderId = orderId; }
    public String getProvider() { return provider; }
    public void setProvider(String provider) { this.provider = provider; }
    public PaymentStatus getStatus() { return status; }
    public void setStatus(PaymentStatus status) { this.status = status; }
    public String getProviderStatus() { return providerStatus; }
    public void setProviderStatus(String providerStatus) { this.providerStatus = providerStatus; }
    public String getMerchantPaymentId() { return merchantPaymentId; }
    public void setMerchantPaymentId(String merchantPaymentId) { this.merchantPaymentId = merchantPaymentId; }
    public Integer getAmount() { return amount; }
    public void setAmount(Integer amount) { this.amount = amount; }
    public String getCurrency() { return currency; }
    public void setCurrency(String currency) { this.currency = currency; }
    public String getPaypayCodeId() { return paypayCodeId; }
    public void setPaypayCodeId(String paypayCodeId) { this.paypayCodeId = paypayCodeId; }
    public String getPaypayPaymentId() { return paypayPaymentId; }
    public void setPaypayPaymentId(String paypayPaymentId) { this.paypayPaymentId = paypayPaymentId; }
    public String getPaymentUrl() { return paymentUrl; }
    public void setPaymentUrl(String paymentUrl) { this.paymentUrl = paymentUrl; }
    public String getDeeplink() { return deeplink; }
    public void setDeeplink(String deeplink) { this.deeplink = deeplink; }
    public OffsetDateTime getExpiresAt() { return expiresAt; }
    public void setExpiresAt(OffsetDateTime expiresAt) { this.expiresAt = expiresAt; }
    public OffsetDateTime getPaidAt() { return paidAt; }
    public void setPaidAt(OffsetDateTime paidAt) { this.paidAt = paidAt; }
    public OffsetDateTime getLastSyncedAt() { return lastSyncedAt; }
    public void setLastSyncedAt(OffsetDateTime lastSyncedAt) { this.lastSyncedAt = lastSyncedAt; }
    public String getRawCreateResponse() { return rawCreateResponse; }
    public void setRawCreateResponse(String rawCreateResponse) { this.rawCreateResponse = rawCreateResponse; }
    public String getRawStatusResponse() { return rawStatusResponse; }
    public void setRawStatusResponse(String rawStatusResponse) { this.rawStatusResponse = rawStatusResponse; }
    public OffsetDateTime getCreatedAt() { return createdAt; }
    public OffsetDateTime getUpdatedAt() { return updatedAt; }
}
