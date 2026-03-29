# Design System Tokens

## Core Visual Foundation
This document defines the atomic tokens for the Quantum Swarm Todo MVP. All UI components (Button, Input, Card) must consume these tokens to ensure design consistency.

### Color Palette
- **Brand:** Primary: `#2563EB` | Secondary: `#1D4ED8`
- **Neutral:** Background: `#FFFFFF` | Subtle: `#F4F4F5` | Text: `#18181B` | Muted: `#71717A`
- **Status:** Error: `#EF4444` | Success: `#22C55E` | Warning: `#F59E0B`
- **Focus:** `#3B82F6` (Use for keyboard navigation)

### Spacing (8px Grid)
- **XS:** 4px
- **SM:** 8px
- **MD:** 16px
- **LG:** 24px
- **XL:** 32px

### Typography
- **Primary Font:** Inter, sans-serif
- **Mono Font:** JetBrains Mono, monospace
- **Scale:** Standardized via body/heading roles.

### Border & Elevation
- **Radius:** 4px (Button/Input) | 8px (Cards)
- **Shadow:** 0px 1px 3px rgba(0,0,0,0.1) (Subtle depth)

---
### Integration Notes
- Engineers: Use these variables in your CSS/Tailwind configuration. 
- UI Designer: Ensure all components reference these tokens. Do not hardcode hex values.
