# Take turns

A web application to let a group of people take turns.

Written with Flask and deployed on GCP using App Engine and Cloud storage.

# Run it yourself

Before being able to run the app yourself, you'll need to make sure you have:

- A GCP project
- An App Engine app (see [docs](https://cloud.google.com/appengine/docs/standard/python3/quickstart))
- A Cloud Storage Bucket

## Run locally

- Make sure you have Python 3.7 (might also work with 3.6 or 3.8. I didn't test it)
- Install the requirements
- run
```
export FLASK_RUN_PORT=8080
export FLASK_APP=main.py
flask run
```
- Check http://localhost:8080

> ## Note
> If you want to run locally but store your data on Cloud Storage (see [the
configuration section](#configuration) below), you'll also need to set up
> gcloud and set application credentials.
>
> - Set up gcloud (see [the docs](https://cloud.google.com/sdk/docs/initializing))
> - Log in by running `gcloud auth login`
> - Set application credentials by running `gcloud auth application-default login`

## Deploy to App Engine

### Configuration

Set the following environment variables in [the app engine config file](./app.yaml):

- `GCS_BUCKET`: the name of your cloud storage bucket. When set to an empty string, a local file will be used.
- `GCS_OBJECT_NAME`: the name of the file that will be written in your bucket (default `data.json`)
- `ASSIGNMENT_WEEKDAY_START`: on which weekday should the assignment start? (default 0: Monday)
- `ASSIGNMENT_INTERVAL_DAYS`: the interval: the number of days until the next turn (default 7)
- `ALLOW_ASSIGNMENT_TO_START_TODAY`: whether you allow the assignment to start today (default False)

### Deploy

Run:

```
gcloud app deploy --project=YOUR_PROJECT_ID
```

This will upload your files to app engine and start your app.
When this command finishes, it will point you to the url of your app (typically https://YOUR_PROJECT_ID.appspot.com)

# Endpoints

## `/`
 
Get all users and assignment dates, ordered by date

## `/users/<username>`

 * GET: Get the assignment date for a given user,
 * PUT: Add a new user to the group,
 * DELETE: Remove a user from the group and correct the dates for the remaining users

## `/new`

Start a new assignment (reset all dates)

## `/lookup`

Search for users that are assigned at a given period of time (default: next)

## `/delay`

Delay assignment dates

## `/swap`

Swap to users assignment dates

## `/dialogflow`

Endpoint to integrate with Google Cloud's Dialogflow