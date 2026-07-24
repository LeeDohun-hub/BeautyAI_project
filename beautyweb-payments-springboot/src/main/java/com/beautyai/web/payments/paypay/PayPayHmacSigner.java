package com.beautyai.web.payments.paypay;

import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Clock;
import java.util.Base64;
import java.util.UUID;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.stereotype.Component;

@Component
public class PayPayHmacSigner {
    private static final String EMPTY = "empty";
    private static final String HMAC_SHA256 = "HmacSHA256";

    private final PayPayProperties properties;
    private final Clock clock;

    public PayPayHmacSigner(PayPayProperties properties) {
        this(properties, Clock.systemUTC());
    }

    PayPayHmacSigner(PayPayProperties properties, Clock clock) {
        this.properties = properties;
        this.clock = clock;
    }

    public String sign(String requestUri, String httpMethod, String requestBody) {
        String nonce = UUID.randomUUID().toString().replace("-", "").substring(0, 8);
        String epoch = String.valueOf(clock.instant().getEpochSecond());
        String contentType = hasBody(requestBody) ? properties.getContentType() : EMPTY;
        String hash = hasBody(requestBody) ? md5Base64(contentType, requestBody) : EMPTY;
        String dataToSign = String.join("\n", requestUri, httpMethod, nonce, epoch, contentType, hash);
        String macData = hmacSha256Base64(dataToSign, properties.getApiSecret());
        return "hmac OPA-Auth:%s:%s:%s:%s:%s".formatted(properties.getApiKey(), macData, nonce, epoch, hash);
    }

    private boolean hasBody(String requestBody) {
        return requestBody != null && !requestBody.isEmpty();
    }

    private String md5Base64(String contentType, String requestBody) {
        try {
            MessageDigest md = MessageDigest.getInstance("MD5");
            md.update(contentType.getBytes(StandardCharsets.UTF_8));
            md.update(requestBody.getBytes(StandardCharsets.UTF_8));
            return Base64.getEncoder().encodeToString(md.digest());
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("MD5 algorithm is unavailable", e);
        }
    }

    private String hmacSha256Base64(String dataToSign, String secret) {
        try {
            SecretKeySpec signingKey = new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), HMAC_SHA256);
            Mac mac = Mac.getInstance(HMAC_SHA256);
            mac.init(signingKey);
            return Base64.getEncoder().encodeToString(mac.doFinal(dataToSign.getBytes(StandardCharsets.UTF_8)));
        } catch (GeneralSecurityException e) {
            throw new IllegalStateException("Failed to create PayPay HMAC signature", e);
        }
    }
}
