package com.beautyai.web.payments.postal;

public record PostalCodeResponse(
    String postalCode,
    String prefecture,
    String city,
    String town,
    String address,
    String prefectureKana,
    String cityKana,
    String townKana
) {
}
