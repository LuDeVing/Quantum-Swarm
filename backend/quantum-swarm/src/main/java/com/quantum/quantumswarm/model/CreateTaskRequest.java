package com.quantum.quantumswarm.model;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Positive;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.Setter;

@Setter
@Getter
@AllArgsConstructor
public class CreateTaskRequest {

    @NotBlank
    private String text;

    @Positive
    private  int tokenBudget;
}
