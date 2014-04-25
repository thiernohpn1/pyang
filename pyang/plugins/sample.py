# Copyright (c) 2014 by Ladislav Lhotka, CZ.NIC <lhotka@nic.cz>
#
# Pyang plugin generating a XSLT1 stylesheet for XML->JSON translation.
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

"""sample output plugin

This plugin takes a YANG data model and generates an XML instance
document containing sample elements for all data nodes.

* An element is present for every leaf, container or anyxml.

* At least one element is present for every leaf-list or list. The
  number of entries in the sample is min(1, min-elements).

* For a choice node, sample element(s) are present for each case.

* Leaf, leaf-list and anyxml elements are empty (exception:
  --sample-defaults option).
"""

import os
import sys
import optparse
import xml.etree.ElementTree as ET
import copy

from pyang import plugin, statements, error
from pyang.util import unique_prefixes

def pyang_plugin_init():
    plugin.register_plugin(SamplePlugin())

class SamplePlugin(plugin.PyangPlugin):

    def add_opts(self, optparser):
        optlist = [
            optparse.make_option("--sample-doctype",
                                 dest="doctype",
                                 default="data",
                                 help="Type of sample XML document (data or config)."),
            optparse.make_option("--sample-defaults",
                                 action="store_true",
                                 dest="sample_defaults",
                                 default=False,
                                 help="Insert leafs with defaults values."),
            optparse.make_option("--sample-annots",
                                 action="store_true",
                                 dest="sample_annots",
                                 default=False,
                                 help="Add annotations as XML comments."),
            ]
        g = optparser.add_option_group("Sample output specific options")
        g.add_options(optlist)
    def add_output_format(self, fmts):
        self.multiple_modules = True
        fmts['sample'] = self

    def setup_fmt(self, ctx):
        ctx.implicit_errors = False

    def emit(self, ctx, modules, fd):
        """Main control function.

        Set up the top-level parts of the sample doument, then process
        recursively all nodes in all data trees, and finally emit the
        sample XML document.
        """
        for (epos, etag, eargs) in ctx.errors:
            if error.is_error(error.err_level(etag)):
                raise error.EmitError("Sample plugin needs a valid module")
        if ctx.opts.doctype not in ("config", "data"):
            raise error.EmitError("Unsupported document type: %s" %
                                  ctx.opts.doctype)
        self.annots = ctx.opts.sample_annots
        self.defaults = ctx.opts.sample_defaults
        self.node_handler = {
            "container": self.container,
            "leaf": self.leaf,
            "anyxml": self.anyxml,
            "choice": self.process_children,
            "case": self.process_children,
            "list": self.list,
            "leaf-list": self.leaf_list,
            "rpc": self.ignore,
            "notification": self.ignore
            }
        self.ns_uri = { yam : yam.search_one("namespace").arg for yam in modules }
        self.top = ET.Element(ctx.opts.doctype,
                         {"xmlns:nc": "urn:ietf:params:xml:ns:netconf:base:1.0"})
        tree = ET.ElementTree(self.top)
        for yam in modules:
            self.currmod = None
            self.process_children(yam, self.top)
        tree.write(fd, encoding="utf-8" if sys.version < "3" else "unicode",
                   xml_declaration=True)

    def ignore(self, node, elem):
        """Do nothing for `node`."""
        pass

    def process_children(self, node, elem):
        """Proceed with all children of `node`."""
        for ch in node.i_children:
            self.node_handler[ch.keyword](ch, elem)

    def container(self, node, elem):
        """Create a sample container element and proceed with its children."""
        nel = self.sample_element(node, elem)
        if self.annots:
            pres = node.search_one("presence")
            if pres is not None:
                nel.append(ET.Comment(" presence: %s " % pres.arg))
        self.process_children(node, nel)

    def leaf(self, node, elem):
        """Create a sample leaf element."""
        if node.i_default is None:
            nel = self.sample_element(node, elem)
            if self.annots:
                nel.append(ET.Comment(" type: %s " % node.search_one("type").arg))
        elif self.defaults:
            nel = self.sample_element(node, elem)
            nel.text = str(node.i_default)

    def anyxml(self, node, elem):
        """Create a sample anyxml element."""
        nel = self.sample_element(node, elem)
        if self.annots:
            nel.append(ET.Comment(" anyxml "))

    def list(self, node, elem):
        """Create sample entries of a list."""
        nel = self.sample_element(node, elem)
        self.process_children(node, nel)
        minel = node.search_one("min-elements")
        self.add_copies(node, elem, nel, minel)
        self.list_comment(node, nel, minel)

    def leaf_list(self, node, elem):
        """Create sample entries of a leaf-list."""
        nel = self.sample_element(node, elem)
        minel = node.search_one("min-elements")
        self.add_copies(node, elem, nel, minel)
        self.list_comment(node, nel, minel)

    def sample_element(self, node, parent):
        """Create element under `parent`.

        Declare new namespace if necessary.
        """
        res = ET.SubElement(parent, node.arg)
        mm = node.main_module()
        if mm != self.currmod:
            res.attrib["xmlns"] = self.ns_uri[mm]
            self.currmod = mm
        return res

    def add_copies(self, node, parent, elem, minel):
        """Add appropriate number of `elem` copies to `parent`."""
        rep = 0 if minel is None else int(minel.arg) - 1
        for i in range(rep):
            parent.append(copy.deepcopy(elem))

    def list_comment(self, node, elem, minel):
        """Add list annotation to `elem`."""
        if not self.annots: return
        lo = "0" if minel is None else minel.arg
        maxel = node.search_one("max-elements")
        hi = "" if maxel is None else maxel.arg
        elem.insert(0, ET.Comment(" # entries: %s..%s " % (lo,hi)))

