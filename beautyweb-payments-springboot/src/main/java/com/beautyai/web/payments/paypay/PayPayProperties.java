package com.beautyai.web.payments.paypay;

import java.util.Map;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

@Validated
@ConfigurationProperties(prefix = "paypay")
public class PayPayProperties {
    private String environment = "sandbox";
    private String apiKey = "";
    private String apiSecret = "";
    private String merchantId = "";
    private String storeId = "beautyai-web";
    private String terminalId = "web";
    private String orderDescriptionPrefix = "BeautyAI";
    private String contentType = "application/json;charset=UTF-8;";
    private int connectTimeoutMs = 5000;
    private int readTimeoutMs = 35000;
    private Map<String, String> baseUrls = Map.of(
        "sandbox", "https://apigw.sandbox.paypay.ne.jp",
        "staging", "https://apigw.stg.paypay.ne.jp",
        "production", "https://apigw.paypay.ne.jp"
    );

    public String baseUrl() {
        return baseUrls.getOrDefault(environment, baseUrls.get("sandbox"));
    }

    public void validateConfigured() {
        if (isBlank(apiKey) || isBlank(apiSecret) || isBlank(merchantId)) {
            throw new IllegalStateException("PAYPAY_API_KEY, PAYPAY_API_SECRET, and PAYPAY_MERCHANT_ID are required");
        }
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }

    public String getEnvironment() { return environment; }
    public void setEnvironment(String environment) { this.environment = environment; }
    public String getApiKey() { return apiKey; }
    public void setApiKey(String apiKey) { this.apiKey = apiKey; }
    public String getApiSecret() { return apiSecret; }
    public void setApiSecret(String apiSecret) { this.apiSecret = apiSecret; }
    public String getMerchantId() { return merchantId; }
    public void setMerchantId(String merchantId) { this.merchantId = merchantId; }
    public String getStoreId() { return storeId; }
    public void setStoreId(String storeId) { this.storeId = storeId; }
    public String getTerminalId() { return terminalId; }
    public void setTerminalId(String terminalId) { this.terminalId = terminalId; }
    public String getOrderDescriptionPrefix() { return orderDescriptionPrefix; }
    public void setOrderDescriptionPrefix(String orderDescriptionPrefix) { this.orderDescriptionPrefix = orderDescriptionPrefix; }
    public String getContentType() { return contentType; }
    public void setContentType(String contentType) { this.contentType = contentType; }
    public int getConnectTimeoutMs() { return connectTimeoutMs; }
    public void setConnectTimeoutMs(int connectTimeoutMs) { this.connectTimeoutMs = connectTimeoutMs; }
    public int getReadTimeoutMs() { return readTimeoutMs; }
    public void setReadTimeoutMs(int readTimeoutMs) { this.readTimeoutMs = readTimeoutMs; }
    public Map<String, String> getBaseUrls() { return baseUrls; }
    public void setBaseUrls(Map<String, String> baseUrls) { this.baseUrls = baseUrls; }
}
