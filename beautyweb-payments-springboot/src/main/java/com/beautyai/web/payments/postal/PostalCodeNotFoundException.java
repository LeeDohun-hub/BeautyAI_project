package com.beautyai.web.payments.postal;

public class PostalCodeNotFoundException extends RuntimeException {
    public PostalCodeNotFoundException(String postalCode) {
        super("Postal code not found: " + postalCode);
    }
}
