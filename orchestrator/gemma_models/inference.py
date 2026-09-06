import litert_lm as llm
llm.set_min_log_severity(llm.LogSeverity.ERROR)
with llm.Engine(
    "./gemma-4-E2B-it.litertlm"
    ) as engine:
    with engine.create_conversation() as convo:
        
        while True:
            user_input=input("\n>>>")
            for chunk in convo.send_message_async(user_input):
                print(chunk["content"][0]["text"],end="",flush=True)
