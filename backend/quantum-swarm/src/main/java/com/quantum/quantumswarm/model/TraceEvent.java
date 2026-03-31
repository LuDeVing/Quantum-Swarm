package com.quantum.quantumswarm.model;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.Setter;

import java.sql.Timestamp;

@Setter
@Getter
@AllArgsConstructor
public class TraceEvent {
    private String agent;
    private String event;
    private  String  energy;
    private Timestamp timestamp;

}
