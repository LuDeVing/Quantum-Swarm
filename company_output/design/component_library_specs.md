# Task MVP Component Library Specifications

This document provides the technical specification for core components.
All components must adhere to the Design Token system.

## 1. Button
- **States:** Default, Hover, Active, Disabled, Loading
- **Props:** 
  - `variant`: 'primary' | 'secondary' | 'danger'
  - `size`: 'small' | 'medium'
  - `isLoading`: boolean
- **Interaction:**
  - `primary` (default): #0070F3, Hover: #0060D9, Active: #0050B3
  - `danger`: #E00, Hover: #C00, Active: #A00
  - `disabled`: #EAEAEA, Text: #999

## 2. Input
- **States:** Default, Focus, Error, Disabled
- **Props:**
  - `value`: string
  - `onChange`: (val: string) => void
  - `placeholder`: string
  - `hasError`: boolean
- **Interaction:**
  - Focus: border #0070F3, outline-offset 2px
  - Error: border #E00

## 3. Card (Task Item)
- **Props:**
  - `task`: { id: string, title: string, status: 'PENDING' | 'COMPLETED' }
  - `onToggle`: (id: string) => void
  - `onDelete`: (id: string) => void
- **Visuals:**
  - Border: 1px solid #EAEAEA, Radius: 8px
  - Padding: 16px, Gap: 12px
  - `opacity`: 0.6 (if optimistic pending), 1.0 (synced)

## 4. Modal (Confirmation/Prompt)
- **Props:**
  - `isOpen`: boolean
  - `onClose`: () => void
  - `children`: ReactNode
- **Visuals:**
  - Overlay: rgba(0,0,0,0.5)
  - Background: #FFF, Radius: 12px
  - Box-shadow: 0 4px 12px rgba(0,0,0,0.1)

## Implementation Note
Use these specs with defined tokens. Ensure all interactive states include 200ms transitions.
Accessibility: All inputs must have associated labels. Focus management required for Modals.
