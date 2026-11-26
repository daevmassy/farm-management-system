# Render Deployment

The Render Blueprint in `render.yaml` provisions the Flask web service, a
managed PostgreSQL database, and persistent storage for uploaded files.

## Deploy

1. Push this repository to GitHub.
2. In Render, choose **New > Blueprint** and connect this repository.
3. Review the paid web, database, and disk plans, then create the resources.

Render supplies `DATABASE_URL` from the PostgreSQL service and generates
`SESSION_SECRET`. On startup, the app initializes its schema from
`database/schema_fms.sql`. The web process binds to Render's `PORT`.

The disk is mounted at `static/uploads`; attachments, profile images, and farm
logos are stored there so they survive service redeploys. The database is
private to the Render service and should be kept in the same region as the web
service.
