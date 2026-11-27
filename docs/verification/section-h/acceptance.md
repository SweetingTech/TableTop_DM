# In-world parties and transferable opportunities

| Criterion | Exercised behavior | Verification |
| --- | --- | --- |
| H1 | A character forms a party, invites a nearby resident, and waits for their consent. Departure, hostility, and reunion retain their causal history. | [Party API](../../../tests/unit/kernel/test_party_api.py) and [durable party tests](../../../tests/integration/test_party.py) |
| H2 | An ordinary resident accepts or declines the same offer under different pinned personas. The PostgreSQL worker restarts before deciding. A player denied access to the resident before joining is still denied after joining. | [Resident decisions](../../../tests/unit/kernel/test_party_runtime.py) and [durable restart](../../../tests/integration/test_party_runtime.py) |
| H3 | The leader sets a waypoint, the resident agrees and walks one step under their own controller, and another member receives leadership. Donated inventory can be collected only at the cache. A party member beyond whispering distance misses that testimony. | [Coordination API](../../../tests/unit/kernel/test_party_coordination.py) and [durable coordination](../../../tests/integration/test_party_coordination.py) |
| H4 | After the original giver dies through normal damage and death saves, an authorized alternate offers the task. A body without the required item cannot accept. A committed walk completes the alternate route. The holder offers it to the resident, who consents and claims the original escrow once. | [Quest transfer](../../../tests/unit/kernel/test_quest_transfer_api.py) and [durable transfer](../../../tests/integration/test_quest_transfer.py) |
| H5 | The resident joins and follows an agreed plan as an NPC. The player uses an explicitly authorized controller to resume as that body, leaves to help their brother on night watch, and takes over the finished ford task after the steward dies. Restart preserves the payout receipt and replay verifies the branch. | [Resident campaign](../../../tests/integration/test_quest_transfer.py) |

Run the reference and PostgreSQL lanes from the repository root using the
[test environment](../../TESTING.md).

```powershell
uv run pytest tests/unit/kernel/test_party_api.py tests/unit/kernel/test_party_runtime.py tests/unit/kernel/test_party_coordination.py tests/unit/kernel/test_quest_transfer_api.py -q
$env:TTDM_INTEGRATION = '1'
uv run pytest tests/integration/test_party.py tests/integration/test_party_runtime.py tests/integration/test_party_coordination.py tests/integration/test_quest_transfer.py -v
```

The fixtures use the standard command bus, identity endpoints, clocks, runtime, PostgreSQL
storage, and replay. The fixture provisions equipment through a test-only typed setup command.
Actual body actions supply objective evidence.
