package com.beautyai.web.payments.postal;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/web/postal-codes")
public class PostalCodeController {
    private final PostalCodeService postalCodeService;

    public PostalCodeController(PostalCodeService postalCodeService) {
        this.postalCodeService = postalCodeService;
    }

    @GetMapping("/{postalCode}")
    public PostalCodeResponse find(@PathVariable String postalCode) {
        return postalCodeService.findJapaneseAddress(postalCode);
    }
}
