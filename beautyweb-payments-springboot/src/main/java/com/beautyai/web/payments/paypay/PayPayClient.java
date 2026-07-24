package com.beautyai.web.payments.paypay;

import com.beautyai.web.payments.paypay.dto.PayPayCreateCodeRequest;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.netty.channel.ChannelOption;
import java.time.Duration;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.netty.http.client.HttpClient;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;

@Component
public class PayPayClient {
    private final PayPayProperties properties;
    private final PayPayHmacSigner signer;
    private final ObjectMapper objectMapper;
    private final WebClient webClient;

    public PayPayClient(PayPayProperties properties, PayPayHmacSigner signer, ObjectMapper objectMapper) {
        this.properties = properties;
        this.signer = signer;
        this.objectMapper = objectMapper;
        HttpClient httpClient = HttpClient.create()
            .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, properties.getConnectTimeoutMs())
            .responseTimeout(Duration.ofMillis(properties.getReadTimeoutMs()));
        this.webClient = WebClient.builder()
            .baseUrl(properties.baseUrl())
            .clientConnector(new ReactorClientHttpConnector(httpClient))
            .build();
    }

    public JsonNode createCode(PayPayCreateCodeRequest request) {
        properties.validateConfigured();
        String path = "/v2/codes";
        String body = writeJson(request);
        return webClient.post()
            .uri(path)
            .header(HttpHeaders.AUTHORIZATION, signer.sign(path, HttpMethod.POST.name(), body))
            .header(HttpHeaders.CONTENT_TYPE, properties.getContentType())
            .header("X-ASSUME-MERCHANT", properties.getMerchantId())
            .bodyValue(body)
            .exchangeToMono(response -> response.bodyToMono(String.class).defaultIfEmpty("").map(raw -> {
                if (response.statusCode().isError()) {
                    throw new PayPayApiException(response.statusCode().value(), raw);
                }
                return readJson(raw);
            }))
            .block();
    }

    public JsonNode getPaymentDetails(String merchantPaymentId) {
        properties.validateConfigured();
        String path = "/v2/codes/payments/" + merchantPaymentId;
        return webClient.get()
            .uri(path)
            .header(HttpHeaders.AUTHORIZATION, signer.sign(path, HttpMethod.GET.name(), null))
            .header("X-ASSUME-MERCHANT", properties.getMerchantId())
            .exchangeToMono(response -> response.bodyToMono(String.class).defaultIfEmpty("").map(raw -> {
                if (response.statusCode().isError()) {
                    throw new PayPayApiException(response.statusCode().value(), raw);
                }
                return readJson(raw);
            }))
            .block();
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception e) {
            throw new IllegalArgumentException("Failed to serialize PayPay request", e);
        }
    }

    private JsonNode readJson(String raw) {
        try {
            return objectMapper.readTree(raw);
        } catch (Exception e) {
            throw new IllegalArgumentException("Failed to parse PayPay response", e);
        }
    }
}
