package com.beautyai.web.payments.postal;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.Test;
import org.springframework.web.reactive.function.client.WebClient;

class PostalCodeServiceTest {
    @Test
    void rejectsInvalidPostalCodeBeforeCallingExternalApi() {
        PostalCodeService service = new PostalCodeService(WebClient.builder());

        assertThatThrownBy(() -> service.findJapaneseAddress("150-000"))
            .isInstanceOf(IllegalArgumentException.class)
            .hasMessageContaining("7 digits");
    }

    @Test
    void responseCanRepresentNerimaTagaraPostalCode() {
        PostalCodeResponse response = new PostalCodeResponse(
            "179-0073",
            "東京都",
            "練馬区",
            "田柄",
            "東京都練馬区田柄",
            "トウキョウト",
            "ネリマク",
            "タガラ"
        );

        assertThat(response.postalCode()).isEqualTo("179-0073");
        assertThat(response.address()).isEqualTo("東京都練馬区田柄");
    }
}
