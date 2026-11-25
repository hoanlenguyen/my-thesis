# Boundary cases for the full-text protocol (synthetic, for the author's agreement)

Short synthetic reports on the edges of `screening_protocol.md`. If you disagree with an expected decision, the rule
behind it needs rewording before the pilot.

### Case 1 (synthetic): clear include
A household types its plan ("dishwasher done by 7, car charged to 80% by 8"); GPT-4o turns it into constraints for a
MILP. Tested on 120 requests from 30 households; constraint accuracy 0.91 against hand-labelled answers.
Expected: include (INC). Role: requests into constraints. Setting: home. Evaluation: test set with a measure.

### Case 2 (synthetic): LQ3 rule, no energy objective
A 3B model on a Raspberry Pi maps spoken commands ("lights off in the kitchen") to Home Assistant service calls.
Accuracy on 500 commands and latency per command are reported; a cloud model is the comparator.
Expected: include (INC). Small, local model controlling smart-home devices; I2 widened, I3 met.

### Case 3 (synthetic): explanation only
An LLM explains in plain language why a reinforcement-learning HVAC controller chose its setpoints; 20 occupants rate
the explanations.
Expected: exclude E2. Evaluated and in a building, but the language model only explains another controller's
decisions. Tests: that E4 passes first and E2 decides.

### Case 4 (synthetic): vision paper in the right setting
A framework in which an LLM agent configures the MPC of a home battery; one example dialogue is shown, no measured
result.
Expected: exclude E4 (kept as background). Tests: the code order (E4 before E1 and E2) and the
"one illustrative example" rule.

### Case 5 (synthetic): grid-scale, cloud model
GPT-4 writes unit-commitment models for a 118-bus test system; optimality gap reported.
Expected: exclude E1. Evaluated, eligible role, but grid-scale without a household or building and a cloud model, so
the LQ3 rule does not apply.

### Case 6 (synthetic): recommendation
An on-premise 7B model suggests "run the washing machine at 13:00 tomorrow" from price forecasts; acceptance by 15
households over 4 weeks is measured.
Expected: include (INC) under the rule (author, 25 November 2026) that a concrete schedule recommendation is an
eligible role.
