---
description: Apply to every single bit of code you write
---
No emojis in any responses
Be clear and consise
Do not overcomplicate answers
Prefer older simpler systems rather than new bleeding edge libraries
Consider known errors before implementation
Conduct internal review before implementation

IF context.txt exists: iterate through to ensure context retention
Do not write tests to fit the code, write code to fit the tests
Write tests before code. Clearly define the goals of programs
Do NOT edit test goals or parameters. For example, if a test covers 99%, dont edit it to cover 90% just to pass the unit test

Follow these coding principles:
{Core Philosophy
Code is a Liability: Minimize the footprint. Prefer "delete-ability" and modularity over complex abstractions.
Clarity > Cleverness: If logic requires a comment to explain how it works, it needs refactoring. Comments are for why.

1. Technical Implementation Standards
Function Design: Prioritize idempotency and determinism. Avoid hidden side effects.

Locality of Behavior (LoB): Keep logic visible within the immediate scope. Avoid deep inheritance or excessive "magic" abstractions.

Error Handling: * No silent failures.

Implement "Sad Path" logic first.

Ensure errors are actionable and include necessary context for observability (logs/traces).

Naming: Use domain-driven, discoverable names. Avoid generic terms like data, info, or manager.

2. Architectural Priorities
Decoupling: Use dependency injection to ensure logic is testable without infrastructure (DB, API) requirements.

Open-Closed Principle: Design modules to be open for extension but closed for modification.

Consistency: Adhere strictly to existing project patterns and linting rules to reduce cognitive load for the team.

3. Change Management
Atomic Commits: Break changes into small, logical units.

Refactor with Purpose: Do not refactor for aesthetic reasons alone; refactor to improve testability, performance, or clarity.

Observability: Every new feature must be measurable. Include hooks for metrics and structured logging.}