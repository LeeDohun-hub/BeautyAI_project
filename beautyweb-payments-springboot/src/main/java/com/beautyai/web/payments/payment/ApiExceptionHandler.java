package com.beautyai.web.payments.payment;

import com.beautyai.web.payments.paypay.PayPayApiException;
import com.beautyai.web.payments.postal.PostalCodeNotFoundException;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class ApiExceptionHandler {
    @ExceptionHandler(PaymentNotFoundException.class)
    ResponseEntity<Map<String, String>> notFound(PaymentNotFoundException e) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of("message", e.getMessage()));
    }

    @ExceptionHandler(PostalCodeNotFoundException.class)
    ResponseEntity<Map<String, String>> postalCodeNotFound(PostalCodeNotFoundException e) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of("message", e.getMessage()));
    }

    @ExceptionHandler({IllegalArgumentException.class, MethodArgumentNotValidException.class})
    ResponseEntity<Map<String, String>> badRequest(Exception e) {
        return ResponseEntity.badRequest().body(Map.of("message", "Invalid payment request"));
    }

    @ExceptionHandler(IllegalStateException.class)
    ResponseEntity<Map<String, String>> configurationError(IllegalStateException e) {
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(Map.of("message", e.getMessage()));
    }

    @ExceptionHandler(PayPayApiException.class)
    ResponseEntity<Map<String, String>> payPayError(PayPayApiException e) {
        HttpStatus status = e.getStatusCode() == 429 ? HttpStatus.TOO_MANY_REQUESTS : HttpStatus.BAD_GATEWAY;
        return ResponseEntity.status(status).body(Map.of("message", "PayPay request failed"));
    }
}
