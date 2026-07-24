package com.beautyai.web.payments;

import com.beautyai.web.payments.paypay.PayPayProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

@SpringBootApplication
@EnableConfigurationProperties(PayPayProperties.class)
public class BeautyWebPaymentsApplication {
    public static void main(String[] args) {
        SpringApplication.run(BeautyWebPaymentsApplication.class, args);
    }
}
