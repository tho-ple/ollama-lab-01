# Order service repair

Work from this directory. Read docs/business-rules.md before changing pricing.
Run `python -m unittest discover -s tests -v`. The original starter baseline had nine
tests (five failed). This repaired version passes all nine acceptance tests and
two additional regression tests. Do not weaken acceptance tests.
The repaired pricing and tests/test_student.py are included.

Keep your agent outside this target directory. This separates its implementation
and permissions from files it is allowed to change. Initialize a local Git
repository here to inspect subsequent changes. To reproduce the original defects,
use the starter ZIP rather than modifying these acceptance tests.
