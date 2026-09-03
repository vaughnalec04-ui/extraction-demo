# Spot-check manifest

10 of 80 records flagged for **manual label verification**. Open each
image next to its expected values below and confirm the label is what a
careful human keyer would record. These were chosen for difficulty, not
at random; they are where label authoring could have gone wrong.

Labels were authored first, in `meridian/dataset/labels.py:author_labels()`,
and each image was rendered from its record. No label is downstream of a
model.

| # | doc | image | stratum | split | what to check |
|---|-----|-------|---------|-------|----------------|
| 1 | `ambi-006` | [`data/docs/ambi-006.jpg`](docs/ambi-006.jpg) | ambiguous | tune | two totals on the page; confirm `TOTAL DUE` is the label and `SUBTOTAL` (3777.47) is NOT |
| 2 | `ambi-009` | [`data/docs/ambi-009.jpg`](docs/ambi-009.jpg) | ambiguous | test | two totals on the page; confirm `TOTAL DUE` is the label and `SUBTOTAL` (6027.02) is NOT |
| 3 | `ambi-001` | [`data/docs/ambi-001.jpg`](docs/ambi-001.jpg) | ambiguous | tune | two totals on the page; confirm `TOTAL DUE` is the label and `TOTAL CHARGES` (674.66) is NOT |
| 4 | `degr-001` | [`data/docs/degr-001.jpg`](docs/degr-001.jpg) | degraded | tune | amount is handwriting-style; confirm every digit is legible and matches |
| 5 | `degr-009` | [`data/docs/degr-009.jpg`](docs/degr-009.jpg) | degraded | test | amount is handwriting-style; confirm every digit is legible and matches |
| 6 | `inco-003` | [`data/docs/inco-003.jpg`](docs/inco-003.jpg) | incomplete | tune | `total_amount` must be absent from the image, not merely faint |
| 7 | `inco-001` | [`data/docs/inco-001.jpg`](docs/inco-001.jpg) | incomplete | tune | `policy_number` must be absent from the image, not merely faint |
| 8 | `ood-001` | [`data/docs/ood-001.jpg`](docs/ood-001.jpg) | ood | tune | wrong doc type; confirm none of the six fields truly appear |
| 9 | `ood-005` | [`data/docs/ood-005.jpg`](docs/ood-005.jpg) | ood | test | wrong doc type; confirm none of the six fields truly appear |
| 10 | `clea-001` | [`data/docs/clea-001.jpg`](docs/clea-001.jpg) | clean | tune | baseline; confirm all six values transcribe exactly |

## Expected values

### `ambi-006`: ambiguous / medical_invoice
- `claim_id` = `CLM-39021`
- `policy_number` = `MP-6094-LV`
- `claimant_name` = `Reuben Castellanos`
- `date_of_service` = `2026-02-26`
- `provider_name` = `Kingsbury Motor Works`
- `total_amount` = `3867.47`
- _distractor on page:_ `SUBTOTAL` = `3777.47` (must NOT be extracted)

### `ambi-009`: ambiguous / claim_form
- `claim_id` = `CLM-61150`
- `policy_number` = `MP-2342-RE`
- `claimant_name` = `Nadia Quintero`
- `date_of_service` = `2026-01-22`
- `provider_name` = `Anders & Pike Diagnostic Labs`
- `total_amount` = `6036.02`
- _distractor on page:_ `SUBTOTAL` = `6027.02` (must NOT be extracted)

### `ambi-001`: ambiguous / claim_form
- `claim_id` = `CLM-21053`
- `policy_number` = `MP-8525-GL`
- `claimant_name` = `Curtis Kowalczyk`
- `date_of_service` = `2026-07-11`
- `provider_name` = `Kingsbury Motor Works`
- `total_amount` = `539.73`
- _distractor on page:_ `TOTAL CHARGES` = `674.66` (must NOT be extracted)

### `degr-001`: degraded / claim_form
- `claim_id` = `CLM-53519`
- `policy_number` = `MP-4012-XT`
- `claimant_name` = `Tomas Hargreaves`
- `date_of_service` = `2026-08-07`
- `provider_name` = `Blackwell Auto Body & Frame`
- `total_amount` = `2272.40`

### `degr-009`: degraded / claim_form
- `claim_id` = `CLM-46918`
- `policy_number` = `MP-6922-LS`
- `claimant_name` = `Marcus Castellanos`
- `date_of_service` = `2026-07-27`
- `provider_name` = `Kingsbury Motor Works`
- `total_amount` = `3766.60`

### `inco-003`: incomplete / adjuster_narrative
- `claim_id` = `CLM-42538`
- `policy_number` = `MP-8589-XG`
- `claimant_name` = `Lourdes Castellanos`
- `date_of_service` = `2026-06-11`
- `provider_name` = `Northgate Orthopedic Associates`
- `total_amount` = **ABSENT (null)**

### `inco-001`: incomplete / claim_form
- `claim_id` = `CLM-43894`
- `policy_number` = **ABSENT (null)**
- `claimant_name` = `Anton Okonkwo`
- `date_of_service` = `2026-02-19`
- `provider_name` = `Kingsbury Motor Works`
- `total_amount` = `1636.15`

### `ood-001`: ood / vehicle_registration
- `claim_id` = **ABSENT (null)**
- `policy_number` = **ABSENT (null)**
- `claimant_name` = **ABSENT (null)**
- `date_of_service` = **ABSENT (null)**
- `provider_name` = **ABSENT (null)**
- `total_amount` = **ABSENT (null)**

### `ood-005`: ood / vehicle_registration
- `claim_id` = **ABSENT (null)**
- `policy_number` = **ABSENT (null)**
- `claimant_name` = **ABSENT (null)**
- `date_of_service` = **ABSENT (null)**
- `provider_name` = **ABSENT (null)**
- `total_amount` = **ABSENT (null)**

### `clea-001`: clean / claim_form
- `claim_id` = `CLM-57457`
- `policy_number` = `MP-1334-VC`
- `claimant_name` = `Dimitri Rasmussen`
- `date_of_service` = `2026-06-01`
- `provider_name` = `Trellis Road Chiropractic`
- `total_amount` = `5052.56`

