# Keying the held-out plans (draft, 21 Nov 2026)

The answer key is what a careful person would set in the gateway from the **message as written**, not from the
scenario card. Writers may leave things out, round times or add details; the key follows their words. The card's
`facts` and `conflict_note` are only a reference for spotting a misread.

Work in `plans_heldout.json` (filled by `collect.py`), one `key` per plan, in the format of
`plan_pilot/plans.json`. Key every plan before any system has seen any held-out message.

## Fields

| Field | Content | Example |
|---|---|---|
| `decision` | `"commit"` if the plan can be applied as written, `"ask"` if a question must be answered first | `"commit"` |
| `ev` | each car charge: `departure`, and `target_pct` **or** `energy_kwh` as the writer gave it; `earliest` only if stated | `{"departure": "2016-03-14 07:30", "target_pct": 80}` |
| `appliances` | `appliance` (`dishwasher` or `washing_machine`), `deadline`, `earliest` only if stated | `{"appliance": "dishwasher", "deadline": "2016-05-24 18:00"}` |
| `away` | `start`, `end` of each period when everyone is out | `{"start": "2016-09-20 18:00", "end": "2016-09-20 22:00"}` |
| `comfort` | `start`, `end`, `min_c` and/or `max_c`, only where the writer names a temperature | `{"start": ..., "end": ..., "min_c": 23}` |
| `clarify` | on an `ask` plan, the topics a good question would be about: `ev`, `appliance`, `away`, `comfort`, `conflict` | `["conflict", "ev"]` |
| `feasible`, `infeasible_because` | on an EV item that the charger cannot meet | see `plan_pilot/plans.json`, X5 |

All times are absolute `YYYY-MM-DD HH:MM`, resolved from the time the message was sent ("tonight", "tomorrow",
"half seven"); "midnight" at the end of a day is 00:00 of the next day.

## Rules (protocol section 5, adopted 1 Nov 2026)

1. **Infeasible or contradictory → ask.** A charge the charger cannot add by the departure (energy needed = (target
   % − current %) / 100 × 40 kWh against 3.7 kW × hours left), an appliance whose cycle (dishwasher 1 h, washing
   machine 2.25 h) does not fit before its deadline, away mode and a warm house over the same hours, or charging
   that needs the grid when the writer rules it out: `decision` `"ask"`, `clarify` includes `"conflict"`. Still list
   the items as asked.
2. **After a change**, the key holds only the requirements still in force from the second message on; items
   already over are dropped. A period that has already started is scored from the time of the change.
3. **Clear parts still count.** On an `ask` plan, list every requirement that is already clear; leave out only the
   vague one, and name its topic in `clarify`.
4. **Away and comfort.** An away period is recorded as such (the gateway applies the 17 °C setback); a comfort
   band only when a temperature is named. "Warmer", "extra warm", "nice and cool" without a number: `ask` with
   `clarify` `["comfort"]`.
5. **Defaults the app knows.** "The usual charge", "as usual" or a charge request without a target or time: 80 %
   by 07:30 (the household's setting), which needs no question. A request that gives a time but no amount, or an
   amount but no time, and is not "the usual": `ask` with `clarify` `["ev"]`.
6. **Vague words** ("early", "a few hours", "sometime", "well charged", "enough for the trip"): `ask`, unless the
   rest of the message pins the value down. An appliance "today" or "tonight" without a time is keyed to the
   end of that day (00:00 of the next day), as in the pilot's A5, and needs no question. "Sometime" or "whenever
   it's cheap" with no day at all: `ask` with `clarify` `["appliance"]`.
7. **When in doubt** between two readings, write both in a `note` field and settle it with the second person;
   don't guess.

Check every key with the self-test (it scores the keys against themselves and checks EV feasibility flags against
the charger):

```
uv run python prototypes/plan_pilot/pilot.py --self-test --plans prototypes/heldout/plans_heldout.json
```

## Second person's check

A second person who has not seen the author's keys keys all 120 plans from the messages alone, with this guide,
into `plans_heldout_check.json` (same format, `collect.py` output copied, keys emptied). Then:

1. compare the two (`decision`, each item, `clarify` topics); report the agreement before resolving it (Cohen's
   kappa on `decision`, the share of items keyed identically);
2. resolve each disagreement by discussion; record the plan, both readings and the outcome in
   `key_disagreements.md`; if a rule above had to be made more precise, record the new wording there too;
3. the resolved keys in `plans_heldout.json` are the answer key. They are registered (committed) together with
   the hypotheses, thresholds and the frozen run configuration, before any system reads a held-out message.
