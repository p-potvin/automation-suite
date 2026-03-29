# Contributing to VaultWares

Welcome! To maintain code quality and security standards, please follow these guidelines when using Gemini Code Assist or writing manual code.

## 🏗️ Folder Structure
- `/app`: Next.js App Router (Pages and API routes).
- `/components/ui`: Atomic Shadcn components (Do not modify directly).
- `/components/features`: Feature-specific logic (e.g., `/cart`, `/checkout`).
- `/hooks`: Custom React hooks.
- `/lib`: Utility functions and shared Zod schemas.
- `/types`: Global TypeScript interfaces.

## ✍️ Coding Standards
1. **No `any`:** Use strict TypeScript types. Use `interface` for objects and `type` for unions/primitives.
2. **Component Exports:** Use named exports.
   ```tsx
   export const ProductCard = ({ name }: ProductProps) => { ... }
   ```
3. **Data Fetching:** Prefer Server Components for initial data load. Use TanStack Query for client-side mutations.

4. **Styling:** Use Tailwind utility classes. Follow the 'Glassmorphism' pattern for interactive cards.

## 🛡️ Security Checkpoint

1. **Before submitting a PR:**

    - Does your database query respect RLS?

    - Is all user input sanitized via Zod?

    - Are environment variables properly handled (never committed)?