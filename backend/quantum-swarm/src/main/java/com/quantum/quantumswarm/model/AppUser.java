package com.quantum.quantumswarm.model;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
@AllArgsConstructor
public class AppUser {
    private  String id;
    private String email;
    private String name;
    private AuthProvider authProvider;


}
