import sys
import types
import os

import rich
from rich.prompt import Prompt
from rich.live import Live
from rich.text import Text

from . import printer, chat, utils, storage, errors, parser, session


def fetch_and_cache(messages, params):
    result = chat.query_chat_gpt(messages, params)
    if isinstance(result, types.GeneratorType):
        text = Text("")
        message = None
        with Live(text, refresh_per_second=4) as live:
            for message in result:
                live.update(message.content)
            live.update("")
        response_msg = message
    else:
        response_msg = chat.query_chat_gpt(messages, params)
    messages.append(response_msg)
    storage.to_cache(messages, params.session or utils.scratch_session)
    return messages


def start_repl(messages, params):
    while True:
        try:
            query = Prompt.ask("[yellow]query (type 'quit' to exit): [/yellow]")
        except (EOFError, KeyboardInterrupt):
            rich.print("\n")
            exit()
        if query.lower() == "quit":
            exit()

        if not messages:
            messages = chat.init_conversation(query)
        else:
            messages.append(chat.Message("user", query))

        messages = fetch_and_cache(messages, params)
        printer.print_messages(messages[-1:], params)


def handle_input(query, params):
    utils.debug(title="cli input", query=query, params=params)

    messages = None
    if params.session:
        messages = storage.messages_from_cache(params.session)
    if messages: # a session specified and it alredy exists
      if params.prompt_file:
        printer.warn("refusing to prepend prompt to existing session")
        exit(1)
      if query:  # continue conversation
        messages.append(chat.Message("user", query))
    else:
      init_args = []
      if params.prompt_file:
        init_args.append(storage.load_prompt_file(params.prompt_file))
      if query or init_args:
        messages = chat.init_conversation(query, *init_args)

    if messages:
        if params.tokens:
            token_prices = chat.get_tokens_and_costs(messages)
            printer.print_tokens(messages, token_prices, params)
        else:
            if messages[-1].role == "user":
                messages = fetch_and_cache(messages, params)
            printer.print_messages(messages, params)
    elif params.interactive:
        pass
    else:
        printer.warn("no query or option given. nothing to do...")
        exit()

    if params.interactive:
        start_repl(messages, params)


def do_session_op(sess, op, rename_to):
    if op == "list":
        print(*session.list_sessions(), sep="\n")
        return 0

    err = None
    if not sess:
        err = "session name required"
    elif op == "path" or op == "dump":
        sess_path = storage.get_session_path(sess, True)
        if sess_path:
            if op == "path":
                data = sess_path
            else:
                with open(sess_path, "r") as f:
                    data = f.read()
            print(data)
        else:
            err = "session does not exist"
    elif op == "delete":
        err = session.delete_session(sess)
    elif op == "rename":
        err = session.rename_session(sess, rename_to)
    else:
        raise ValueError(f"unknown session operation: {op}")

    if err:
        printer.warn(err)
        return 1

    return 0


def migrate_old_cahe_file(session):
    cache_path = storage.get_cache_path()
    if os.path.isfile(cache_path):
        printer.warn("old style cache file detected")
        if session == utils.scratch_session:
            printer.warn(f"refusing to migrate old cache file to session '{utils.scratch_session}'")
            printer.warn(f"('{utils.scratch_session}' is special, sessionless queries will overwrite it)")
            return 1
        elif session:
            printer.warn(f"attempting to migrate old cache to session '{session}'...")
            storage.migrate_to_session(session)
            printer.warn("done.")
            return 0
        else:
            printer.warn("please specify a session where the old cache file can be migrated,")
            printer.warn(f"or remove the old cache file at {cache_path}")
            return 1


def cli():
    query, params = parser.parse(sys.argv[1:])
    migrate_res = migrate_old_cahe_file(params.session)
    if migrate_res is not None:
        exit(migrate_res)
    if params.session_op:
        ret = do_session_op(params.session, params.session_op, params.rename_to)
        exit(ret)
    if params.debug:
        utils.CONSOLE_DEBUG_LOGGING = True
    try:
        handle_input(query, params)
    except errors.ChatbladeError as e:
        printer.warn(e)
