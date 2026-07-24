package com.beautyai.web.payments.payment;

import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface PaymentRepository extends JpaRepository<Payment, Long> {
    Optional<Payment> findByPaymentId(String paymentId);
    Optional<Payment> findByMerchantPaymentId(String merchantPaymentId);
    List<Payment> findByOrderIdAndProviderOrderByCreatedAtDesc(String orderId, String provider);
}
