# Render Deployment

The Render Blueprint in `render.yaml` provisions the Flask web service and a
managed PostgreSQL database on Render's free plans.

## Deploy

1. Push this repository to GitHub.
2. In Render, choose **New > Blueprint** and connect this repository.
3. Review the free web and database plans, then create the resources.

Render supplies `DATABASE_URL` from the PostgreSQL service and generates
`SESSION_SECRET`. On startup, the app initializes its schema from
`database/schema_fms.sql`. The web process binds to Render's `PORT`.

Free Render web services use ephemeral storage, so uploaded files are not
preserved across restarts or redeploys. Free PostgreSQL instances expire after
30 days; export or back up the database before expiry, or upgrade to a paid
plan for continued storage. The database should be kept in the same region as
the web service.
