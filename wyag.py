import collections
import configparser
import hashlib
import os
import re
import zlib

git_folder = ".wyag" # ".git"


class GitRepository(object):
    """A git repository"""

    worktree = None
    gitdir = None
    conf = None


    def __init__(self, path, force=False):
        self.worktree = path
        self.gitdir = os.path.join(path, git_folder)

        if not (force or os.path.isdir(self.gitdir)):
            raise Exception("Not a Git repository {:s}".format(self.worktree))

        # read configuration file .git/config
        self.conf = configparser.ConfigParser()
        cf = repo_file(self, "config")

        if cf and os.path.exists(cf):
            self.conf.read([cf])
        elif not force:
            raise Exception("Configuration file is missing")

        if not force:
            vers = int(self.conf.get("core", "repositoryformatversion"))
            if vers != 0:
                raise Exception("Unsupported repositoryformatversion {}".format(vers))



def repo_path(repo, *path):
    """Comput path under repo's gitdir"""
    return os.path.join(repo.gitdir, *path)


def repo_file(repo, *path, mkdir=False):
    """Same as repo_path, but create dirname(*path) if absent. For example,
    repo_file(r, refs, remotes, origin, HEAD) will create .git/refs/remotes/origin."""

    if repo_dir(repo, *path[:-1], mkdir=mkdir):
        return repo_path(repo, *path)


def repo_dir(repo, *path, mkdir=False):
    """Same as repo_path, but mkdir *path if absent if mkdir."""

    path = repo_path(repo, *path)

    if os.path.exists(path):
        if os.path.isdir(path):
            return path
        else:
            raise Exception("Not a directory {}".format(path))

    if mkdir:
        os.makedirs(path)
        return path
    else:
        return None


def repo_create(path):
    """Create a new repository at path."""

    repo = GitRepository(path, True)

    # make sure path doesn't exist or is empty

    if os.path.exists(repo.worktree):
        if not os.path.isdir(repo.worktree):
            raise Exception("{} is not a directroy".format(path))
        if os.listdir(repo.worktree):
            raise Exception("{} is not empty".format(path))
    else:
        os.makedirs(repo.worktree)

    assert(repo_dir(repo, "branches", mkdir=True))
    assert(repo_dir(repo, "objects", mkdir=True))
    assert(repo_dir(repo, "refs", "tags", mkdir=True))
    assert(repo_dir(repo, "refs", "head", mkdir=True))

    # .git/description
    with open(repo_file(repo, "description"), "w") as f:
        f.write("Unnamed repository; edit this file 'description' to name the repository.\n")

    # .git/HEAD
    with open(repo_file(repo, "HEAD"), "w") as f:
        f.write("refs: refs/heads/master\n")

    with open(repo_file(repo, "config"), "w") as f:
        config = repo_default_config()
        config.write(f)
    
    return repo


def repo_default_config():
    ret = configparser.ConfigParser()

    ret.add_section("core")
    ret.set("core", "repositoryformatversion", "0")
    ret.set("core", "filemode", "false")
    ret.set("core", "bare", "false")

    return ret


def repo_find(path=".", required=True):
    path = os.path.realpath(path)

    if os.path.isdir(os.path.join(path, git_folder)):
        return GitRepository(path)

    # search recursive in parent directories
    parent = os.path.realpath(os.path.join(path, ".."))

    if parent == path:
        # re reached root

        if required:
            raise Exception("No git repository")
        else:
            return None

    return repo_find(parent, required)



class GitObject (object):

    repo = None

    def __init__(self, repo, data=None):
        self.repo = repo

        if data != None:
            self.deserialize(data)

    def serialize(self):
        """This function MUST be implemented by subclassses.
        It must read the obkect's contens from self.data, a byte string, and
        do whaterver it takes to conber it into a meaningful representation.
        What exactly that means depends on each subclass."""

        raise Exception("Unimplemented!")

    def deserialize(self, data):
        raise Exception("Unimplemented!")



def object_find(repo, name, fmt=None, follow=True):
    return name



def object_read(repo, sha):
    """Read object object_id from Git repository repo. Return a GitObject
    whose exact type depends on the object."""

    path = repo_file(repo, "objects", sha[:2], sha[2:])

    with open(path, "rb") as f:
        raw = zlib.decompress(f.read())

        # read object type
        x = raw.find(b' ')
        fmt = raw[0:x]

        # read and validate  object size
        y = raw.find(b'\x00', x)
        size = int(raw[x:y].decode("ascii"))
        if size != len(raw)-y-1:
            raise Exception("Malformed object {}: bad length".format(sha))

        # pick correct constructor
        if fmt==b'commit' : c=GitCommit
        elif fmt==b'tree' : c=GitTree
        elif fmt==b'tag' : c=GitTag
        elif fmt==b'blob' : c=GitBlob
        else:
            raise Exception("Unknown type {} for object {}".format(fmt.decode("ascii"), sha))

        return c(repo, raw[y+1:])


def object_write(obj, actually_write=True):
    # serialize object data
    data = obj.serialize()
    
    # add header
    result = obj.fmt + b' ' + str(len(data)).encode() + b'\x00' + data

    # get hash
    sha = hashlib.sha1(result).hexdigest()

    if actually_write:
        # compute path
        path = repo_file(obj.repo, "objects", sha[:2], sha[2:], mkdir=actually_write)

        with open(path, 'wb') as f:
            # compress and write
            f.write(zlib.compress(result))

    return sha

def object_hash(f, fmt, repo=None):
    data = f.read()

    # Choose constructor depnedo on object type foound in header
    if fmt == b'commit' : obj=GitCommit(repo, data)
    elif fmt == b'tree' : obj=GitTree(repo, data)
    elif fmt == b'tag' : obj=GitTag(repo, data)
    elif fmt == b'blob' : obj=GitBlob(repo, data)
    else:
        raise Exception("Unknown type {}".format(fmt))

    return object_write(obj, repo)



class GitBlob(GitObject):
    fmt=b'blob'

    def serialize(self):
        return self.blobdata

    def deserialize(self, data):
        self.blobdata = data


# Key-Value List with Message
def kvlm_parse(raw, start=0, dct=None):
    if not dct:
        dct = collections.OrderedDict()
        # you cannot declare the argument as dct=OrderedDict() or all 
        # call to the function will endlessly grom the same dict

    # we search for the next space and the next newline
    spc = raw.find(b' ', start)
    nl = raw.find(b'\n', start)

    # id space appears before the newline, we have a keyword

    # base case
    # ============
    # If newline appears first(or there is no space at all, in which
    # case find returns -1), we assume a blank line. A blank line
    # means the remainder of the data is the message.
    if (spc < 0) or (nl < spc):
        assert(nl == start)
        dct[b''] = raw[start+1:]
        return dct

    # Recusive case
    # ================
    # we read a key-value pair and recurse for the next. 
    key = raw[start:spc]

    # Find the end of the value. Continuatuon lines begin with a 
    # space, so loop until we find a \n not followed by a space.
    end = start
    while True:
        end = raw.find(b'\n', end + 1)
        if raw[end + 1] != ord(' '):
            break

    # Grab the value 
    # Also, drop the leading space on continuation lines
    value = raw[spc + 1:end].replace(b'\n ', b'\n')

    # do not overwrite existing data contents
    if key in dct:
        if type(dct[key]) == list:
            dct[key].append(value)
        else:
            dct[key] = [dct[key], value]
    else:
        dct[key] = value
    
    return kvlm_parse(raw, start=end+1, dct=dct)


def kvlm_serialize(kvlm):
    ret = b''

    # output fields
    for k in kvlm.keys():
        # skip message itself
        if k==b'':
            continue
        val = kvlm[k]
        # Normalize to a list
        if type(val) != list:
            val = [val]

        for v in val:
            ret += k + b' ' + v.replace(b'\n', b'\n ') + b'\n'
        
    # append message
    ret += b'\n' + kvlm[b'']

    return ret


class GitCommit(GitObject):
    fmt = b'commit'

    def deserialize(self, data):
        self.kvlm = kvlm_parse(data)

    def serialize(self):
        return kvlm_serialize(self.kvlm)


class GitTreeLeaf(object):
    def __init__(self, mode, path, sha):
        self.mode = mode
        self.path = path
        self.sha = sha


def tree_parse_one(raw, start=0):
    # find the space terminator of the mode
    x = raw.find(b' ', start)
    assert(x-start == 5 or x-start == 6)

    # read the mode
    mode = raw[start:x]

    # fin the NULL terminator of the path
    y = raw.find(b'\x00', x)
    
    # read the path
    path = raw[x+1:y]

    # read SHA as binary and convert to hex string
    sha = hex(
        int.from_bytes(
            raw[y+1:y+21], "big"))[2:] # hex add 0x in front, we need to remove that

    return y+21, GitTreeLeaf(mode, path, sha)


def tree_parse(raw):
    pos = 0
    max = len(raw)
    ret = list()
    while pos < max:
        pos, data = tree_parse_one(raw, pos)
        ret.append(data)

    return ret

def tree_serialize(obj):
    ret = b''
    for i in obj.items:
        ret += i.mode
        ret += b' '
        ret += i.path
        ret += b'\x00'
        sha = int(i.sha, 16)
        ret += sha.to_bytes(20, byteorder="big")
    return ret

class GitTree(GitObject):
    fmt = b'tree'

    def deserialize(self, data):
        self.items = tree_parse(data)

    def serialize(self):
        return tree_serialize(self)