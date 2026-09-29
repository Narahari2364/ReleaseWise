# Database Migrations Guide

Owner: Database team (#db)

## Golden rule: expand, then contract

Schema changes must be backward compatible with the previous version of the code, so
that a rollback of the code is always safe. Use the two-phase "expand and contract" pattern:

1. **Expand:** add new columns/tables. Old code ignores them; new code writes to both.
2. **Contract:** in a *later* release (at least one release after the expand), remove the
   old columns once no running code depends on them.

Never rename or drop a column in the same release that stops using it.

## Review requirements

- Every migration needs approval from a member of the Database team.
- Migrations touching tables with more than 10 million rows must be run as an online
  migration using `orbit-migrate --online` and scheduled outside peak hours (peak hours
  are 11:00 to 15:00 ET).

## Is my migration backward compatible?

A migration is backward compatible if the **previous** version of the code can still read
and write the database correctly after the migration runs. Examples:

- Adding a nullable column: compatible.
- Adding an index: compatible.
- Dropping a column the old code reads: NOT compatible.
- Renaming a column: NOT compatible.
- Changing a column type (e.g. int -> string): NOT compatible.

## Rolling back a migration

Every migration must include a tested `down` script. Rolling back a migration requires
approval from the Database on-call, because it may delete data written since the migration.
