package com.beautyai.web.payments.paypay;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import org.junit.jupiter.api.Test;

class PayPayHmacSignerTest {
    @Test
    void signsPostRequestWithBodyHash() {
        PayPayProperties properties = new PayPayProperties();
        properties.setApiKey("APIKeyGenerated");
        properties.setApiSecret("APIKeySecretGenerated");
        PayPayHmacSigner signer = new PayPayHmacSigner(
            properties,
            Clock.fixed(Instant.ofEpochSecond(1579843452L), ZoneOffset.UTC)
        );

        String header = signer.sign("/v2/codes", "POST", "{\"merchantPaymentId\":\"test\"}");

        assertThat(header).startsWith("hmac OPA-Auth:APIKeyGenerated:");
        assertThat(header).contains(":1579843452:");
        assertThat(header).doesNotEndWith(":empty");
    }

    @Test
    void signsGetRequestWithEmptyHash() {
        PayPayProperties properties = new PayPayProperties();
        properties.setApiKey("api-key");
        properties.setApiSecret("api-secret");
        PayPayHmacSigner signer = new PayPayHmacSigner(
            properties,
            Clock.fixed(Instant.ofEpochSecond(1579843452L), ZoneOffset.UTC)
        );

        String header = signer.sign("/v2/codes/payments/BAI-test", "GET", null);

        assertThat(header).startsWith("hmac OPA-Auth:api-key:");
        assertThat(header).endsWith(":empty");
    }
}
