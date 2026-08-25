# Documentation map

Three documents, three different questions:

| Document | Answers | Read it when... |
|---|---|---|
| [`SPEC.md`](SPEC.md) | *Why* is the schema shaped this way? | You're about to change how something is modeled, or you're wondering why it isn't modeled the "obvious" other way. |
| [`SCHEMA.md`](SCHEMA.md) | *What* tables/triggers/views exist? | You need the ER diagram, a table's exact columns, or which trigger enforces which rule. |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | *How* is the app code organized? | You're adding a route, a template, or a JS file, and want to match the existing conventions instead of inventing new ones. |

Deployment has its own doc, next to what it documents:
[`deploy/gcp/README.md`](https://github.com/PostWardenLabs/PostWarden/blob/master/deploy/gcp/README.md)
(provisioning, redeploying, backups, connecting BI tools remotely).

The root [`README.md`](https://github.com/PostWardenLabs/PostWarden#readme)
is the front door — what PostWarden is, how to run it, how to log in.
Start there if you haven't already.

## Keeping this current

`../CLAUDE.md` carries the standing instruction: a feature or schema
change updates the relevant doc(s) above in the same piece of work that
ships it, not as a follow-up. If you're a human making a change instead,
the same rule applies — a design decision that isn't in `SPEC.md` and a
table that isn't in `SCHEMA.md` didn't really happen, as far as the next
person reading this repo is concerned.
