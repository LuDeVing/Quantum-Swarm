package com.quantum.quantumswarm.model;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
@AllArgsConstructor
public class Claim {
    private String  entity;
    private  String assertion;
    private String  confidence;
    private String  sourceType;
    private  boolean verified;

}
