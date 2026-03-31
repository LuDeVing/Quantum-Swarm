package com.quantum.quantumswarm.model;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.util.List;

@AllArgsConstructor
@NoArgsConstructor
@Getter
@Setter
public class TaskRecord {
    private int id;
    private int ownerId;
    private String text;
    private int tokenBudget;
    private int tokensUsed;
    private TaskStatus status;
    private List<Claim> claims;
    private List<TraceEvent> trace;
}