package com.beautyai.web.payments.postal;

import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;

@Service
public class PostalCodeService {
    private final WebClient webClient;

    public PostalCodeService(WebClient.Builder webClientBuilder) {
        this.webClient = webClientBuilder
            .baseUrl("https://zipcloud.ibsnet.co.jp")
            .build();
    }

    public PostalCodeResponse findJapaneseAddress(String rawPostalCode) {
        String normalized = normalize(rawPostalCode);
        JsonNode response = webClient.get()
            .uri(uriBuilder -> uriBuilder.path("/api/search").queryParam("zipcode", normalized).build())
            .retrieve()
            .bodyToMono(JsonNode.class)
            .block();

        JsonNode first = response == null ? null : response.path("results").path(0);
        if (first == null || first.isMissingNode() || first.isNull()) {
            throw new PostalCodeNotFoundException(format(normalized));
        }

        String prefecture = text(first, "address1");
        String city = text(first, "address2");
        String town = text(first, "address3");
        return new PostalCodeResponse(
            format(normalized),
            prefecture,
            city,
            town,
            String.join("", prefecture, city, town),
            text(first, "kana1"),
            text(first, "kana2"),
            text(first, "kana3")
        );
    }

    private String normalize(String rawPostalCode) {
        String digits = rawPostalCode == null ? "" : rawPostalCode.replaceAll("\\D", "");
        if (digits.length() != 7) {
            throw new IllegalArgumentException("Japanese postal code must be 7 digits");
        }
        return digits;
    }

    private String format(String digits) {
        return digits.substring(0, 3) + "-" + digits.substring(3);
    }

    private String text(JsonNode node, String field) {
        JsonNode value = node.path(field);
        return value.isMissingNode() || value.isNull() ? "" : value.asText();
    }
}
