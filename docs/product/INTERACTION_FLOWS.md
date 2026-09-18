# Interaction flows: Sourcely

These flows show how a person moves through the screens in [`WIREFRAMES.md`](WIREFRAMES.md) to finish a job from the [PRD](PRD.md). They describe **user-visible steps and decisions**. What the server does at each step is in [`FLOW_DIAGRAMS.md`](FLOW_DIAGRAMS.md).

All flows are **Proposed**. The server behaviour under IF-4, IF-5 and IF-7 already exists or is specced in the PoC API.

| ID | Flow | Persona | Features |
|---|---|---|---|
| [IF-1](#if-1-first-run-sign-up-to-first-answer) | First run: sign up to first answer | Asker, Admin | F1, F2, F3, F4, F5 |
| [IF-2](#if-2-sign-in-and-password-reset) | Sign in and password reset | All | F1 |
| [IF-3](#if-3-upload-and-processing) | Upload and processing | Curator | F3, F4 |
| [IF-4](#if-4-ask-a-question) | Ask a question | Asker | F5, F9 |
| [IF-5](#if-5-follow-up-question) | Follow-up question | Asker | F6 |
| [IF-6](#if-6-scoped-question) | Scoped question | Asker | F7 |
| [IF-7](#if-7-replace-or-delete-a-document) | Replace or delete a document | Curator | F3 |
| [IF-8](#if-8-invite-a-teammate) | Invite a teammate | Admin | F2 |
| [IF-9](#if-9-create-and-use-an-api-key) | Create and use an API key | Admin, Integrator | F10 |
| [IF-10](#if-10-error-recovery-while-asking) | Error recovery while asking | Asker | F5, F12 |

---

## IF-1. First run: sign up to first answer

**Goal:** a new user gets a cited answer in under 5 minutes (PRD goal G2). This is the activation flow, so every step that can be skipped is skippable.

```mermaid
flowchart TD
    start([Visitor opens Sourcely]) --> hasAccount{Has an account?}
    hasAccount -- Yes --> signin[W1 Sign in]
    hasAccount -- No --> signup[W2 Sign up form]
    signup --> valid{Form valid?}
    valid -- No --> signupErr[Show field errors inline] --> signup
    valid -- Yes --> verify[W2b Check your email]
    verify --> clicked{Link clicked within 24 h?}
    clicked -- No --> resend[Resend email] --> verify
    clicked -- Yes --> hasInvite{Signed up from an invite?}
    hasInvite -- Yes --> joinWs[Join the inviting workspace] --> askEmpty
    hasInvite -- No --> createWs[W3 Name workspace]
    createWs --> invite{Invite teammates now?}
    invite -- Yes --> sendInv[Send invites] --> uploadStep
    invite -- Skip --> uploadStep[W6 Upload first document]
    uploadStep --> uploaded{Uploaded at least one file?}
    uploaded -- Skip --> askEmpty[W8 Ask, empty library state]
    uploaded -- Yes --> processing[Library shows Queued, then Processing]
    processing --> ready{Ready?}
    ready -- Failed --> fixFile[Show reason, offer another file] --> uploadStep
    ready -- Yes --> suggest[W8 Ask with suggested questions]
    suggest --> firstAsk[User asks first question]
    firstAsk --> answer([W9 Cited answer: activation reached])
    askEmpty --> uploadCta[Empty state: Upload documents] --> uploadStep
```

**Design notes**

- The user doesn't need to wait on the Library screen. Ask opens right away, and a toast says "‹title› is ready, ask about it" when processing ends.
- Invited users skip workspace creation and land in the team's workspace, where documents usually already exist.

## IF-2. Sign in and password reset

```mermaid
flowchart TD
    open([Open app]) --> session{Valid session cookie?}
    session -- Yes --> lastWs[Open last used workspace, W8 Ask]
    session -- No --> w1[W1 Sign in]
    w1 --> submit[Submit email and password]
    submit --> locked{Too many failed attempts?}
    locked -- Yes --> wait[Show wait time] --> w1
    locked -- No --> ok{Credentials correct?}
    ok -- No --> generic[Generic error: email or password is incorrect] --> w1
    ok -- Yes --> verified{Email verified?}
    verified -- No --> w2b[W2b Check your email]
    verified -- Yes --> hasWs{Member of any workspace?}
    hasWs -- No --> w3[W3 Create workspace]
    hasWs -- Yes --> lastWs
    w1 -- Forgot? --> reset[Enter email]
    reset --> sent[Always show: if the account exists, a link was sent]
    sent --> link{Link clicked within 1 h?}
    link -- Yes --> newPw[Set new password] --> revoke[All other sessions signed out] --> w1
    link -- Expired --> reset
```

## IF-3. Upload and processing

**Goal:** a Curator adds documents without waiting and always knows each document's state.

```mermaid
flowchart TD
    lib[W5 Library] --> btn[Click Upload]
    btn --> role{Editor or above?}
    role -- No --> hidden[Upload button not shown]
    role -- Yes --> dialog[W6 Upload dialog]
    dialog --> pick[Drop or browse files]
    pick --> check{Each file: type and size OK?}
    check -- No --> reject[Row shows reason, file excluded]
    check -- Yes --> queue[Row shows upload progress]
    reject --> more{More files?}
    queue --> more
    more -- Add more --> pick
    more -- Done --> tags[Optional tags] --> confirm[Upload n files]
    confirm --> close[Dialog closes, rows appear as Queued]
    close --> poll[Library polls status every 3 s]
    poll --> state{Status}
    state -- Processing --> poll
    state -- Ready --> toast[Toast: title is ready, ask about it]
    state -- Failed --> failed[Row shows reason and Retry]
    failed --> retry{User action}
    retry -- Retry --> poll
    retry -- Replace file --> dialog
    retry -- Delete --> gone[Row removed]
```

**Document status as the user sees it**

```mermaid
stateDiagram-v2
    [*] --> Uploading: file chosen
    Uploading --> Queued: upload finished
    Uploading --> [*]: cancelled or rejected
    Queued --> Processing: worker picks it up
    Processing --> Ready: text extracted, chunks embedded
    Processing --> Failed: no text, corrupt file, or timeout
    Failed --> Queued: Retry
    Ready --> Queued: Replace file
    Ready --> [*]: Delete
    Failed --> [*]: Delete
```

## IF-4. Ask a question

**Goal:** the Asker gets an answer they can trust, or a clear "not found".

```mermaid
flowchart TD
    w8[W8 Ask] --> type[Type question]
    type --> len{1 to 2,000 characters?}
    len -- No --> block[Ask button disabled, counter shown] --> type
    len -- Yes --> send[Press Enter]
    send --> thinking[Show question and a typing indicator]
    thinking --> first{First server event}
    first -- HTTP error --> errState[IF-10 error recovery]
    first -- sources, empty --> noAnswer[W10 I couldn't find this]
    first -- sources, not empty --> cards[Source cards appear in the panel]
    cards --> stream[Tokens stream into the answer]
    stream --> stop{User presses Stop?}
    stop -- Yes --> partial[Keep partial answer, show Retry]
    stop -- No --> endEvt{Stream ends with}
    endEvt -- done --> actions[Show feedback, copy, retry]
    endEvt -- error --> interrupted[Keep partial text, show interrupted and Retry]
    actions --> inspect{User checks a citation?}
    inspect -- Yes --> preview[Source preview drawer, passage highlighted]
    inspect -- No --> feedback{Gives feedback?}
    preview --> feedback
    feedback -- Thumbs up --> saved[Saved, thanks shown]
    feedback -- Thumbs down --> reason[Pick a reason, optional comment] --> saved
    noAnswer --> next{User action}
    next -- Rephrase --> type
    next -- Widen scope --> send
    next -- Upload --> w6[W6 Upload dialog]
```

## IF-5. Follow-up question

**Goal:** short follow-ups work without the user repeating context.

```mermaid
flowchart TD
    conv[W9 Conversation with previous answer] --> fu[User types: and for part-time staff?]
    fu --> send[Send]
    send --> rewrite[Server rewrites it into a standalone question]
    rewrite --> show[Show: Searched for parental leave for part-time staff]
    show --> same[Continue as in IF-4 from First server event]
    same --> wrong{Rewrite missed the point?}
    wrong -- Yes --> edit[User clicks Searched for, edits the query, re-asks]
    wrong -- No --> done([Answer])
    edit --> same
```

## IF-6. Scoped question

```mermaid
flowchart TD
    entry{Where does the user start?}
    entry -- Ask screen --> picker[Open scope picker]
    entry -- Document detail --> preset[Ask about this document: scope preset]
    entry -- Search result --> preset2[Ask about this: scope preset to that document]
    picker --> tab{Tab}
    tab -- Documents --> chooseDocs[Tick documents, up to 100]
    tab -- Tags --> chooseTags[Pick tags, all must match]
    chooseDocs --> chips[Chips show above input]
    chooseTags --> chips
    preset --> chips
    preset2 --> chips
    chips --> ask[Ask as in IF-4, filters sent with the request]
    ask --> result{Result}
    result -- Answer --> keep[Scope stays for the conversation]
    result -- Not found --> widen[Offer: Widen scope to all documents]
    widen --> clear[Chips cleared, question re-sent]
```

## IF-7. Replace or delete a document

```mermaid
flowchart TD
    start{Where?} -- Library row menu --> act
    start -- Document detail --> act{Action}
    act -- Replace --> pickFile[Choose new file, same type rules as upload]
    pickFile --> reQueue[Status Queued, version shown as pending]
    reQueue --> reReady{Processing result}
    reReady -- Ready --> swapped[New version live, version number +1]
    reReady -- Failed --> keepOld[Old version stays live, failure shown with reason]
    act -- Delete --> confirm[Dialog names the document and warns that past answers show Source deleted]
    confirm --> sure{Confirm?}
    sure -- Cancel --> start
    sure -- Delete --> removed[Row removed, toast with document title]
    removed --> effect[Search and Ask stop using it immediately]
```

**Design note:** on replace, the old version stays searchable until the new version is Ready. A failed replace never leaves the document empty. This extends the PoC rule "embed before touching the store".

## IF-8. Invite a teammate

```mermaid
flowchart TD
    admin[W12 Members] --> enter[Enter emails and a role]
    enter --> validEmails{Emails valid and not already members?}
    validEmails -- No --> inline[Inline error per email] --> enter
    validEmails -- Yes --> sent[Pending invites listed, emails sent]
    sent --> recv[Invitee opens the link]
    recv --> expired{Expired or used?}
    expired -- Yes --> ask[Page: ask your admin for a new invite]
    expired -- No --> hasAcc{Has an account?}
    hasAcc -- Yes --> signedIn{Signed in as the invited email?}
    signedIn -- No --> switchAcc[Sign in as the invited email]
    switchAcc --> accept
    signedIn -- Yes --> accept[Accept invite]
    hasAcc -- No --> signup[W2 Sign up, email prefilled and locked] --> accept
    accept --> joined([Lands in the workspace, W8 Ask])
```

## IF-9. Create and use an API key

```mermaid
flowchart TD
    keys[W13 API keys] --> create[Create key, enter a name]
    create --> shown[Full key shown once, with curl example]
    shown --> copied[I've copied it]
    copied --> listed[List shows the name and prefix only]
    listed --> use[Integrator calls /search or /ask with Bearer key]
    use --> works{Response}
    works -- 200 --> lastUsed[Last used updates]
    works -- 401 --> checkKey[Key wrong or revoked]
    works -- 429 --> backoff[Wait for Retry-After]
    listed --> revoke[Admin clicks Revoke and confirms]
    revoke --> dead[Key stops working at once]
```

## IF-10. Error recovery while asking

```mermaid
flowchart TD
    ask[Question sent] --> resp{Response}
    resp -- 503 not configured --> cfg{Is the user an admin?}
    cfg -- Yes --> cfgLink[Message with link to settings]
    cfg -- No --> cfgMsg[Message: ask an admin to set up an AI provider]
    resp -- 503 busy --> auto[Wait Retry-After, retry once automatically]
    auto --> again{Works?}
    again -- Yes --> ok([Answer streams])
    again -- No --> manual[Show busy message and Retry]
    resp -- 429 quota --> quota[Show which limit and when it resets]
    resp -- 504 timeout --> manual
    resp -- 502 rejected --> rejected[Show could not answer and Retry]
    resp -- 200 then error event --> partial[Keep partial answer, show interrupted and Retry]
    resp -- network lost --> offline[Offline banner, input disabled until back online]
    manual --> retry[User clicks Retry] --> ask
    rejected --> retry
    partial --> retry
```

**Rules for every error**

- The question text is never lost. It stays in the conversation, and Retry re-sends it.
- Search and the Library keep working when the LLM fails, because they don't need it (SPEC rule: `/documents` and `/search` never need an LLM key).
- Every error message says what happened and what to do next, without technical detail. The request id is shown under "Details" for support.
