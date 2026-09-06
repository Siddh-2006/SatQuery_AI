# we are back to learning command line tools for inferencing this time
# lets gooo
import enum
import click
@click.group()
def cli():
    pass
@cli.command()
def hello():
    click.echo("hello world")
class Hash_type(enum.Enum):
    md5=enum.auto()
    sha256=enum.auto()
@cli.command()
@click.option("--hash-type",type=click.Choice(Hash_type,case_sensitive=False))
def digest(hash_type:Hash_type):
    '''set the hashing algo to hash your chats'''
    click.echo(f"your chats will be hashed with {hash_type}")