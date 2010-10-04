from bson.son import SON
import logging


import helpers
import message

_QUERY_OPTIONS = {
    "tailable_cursor": 2,
    "slave_okay": 4,
    "oplog_replay": 8,
    "no_timeout": 16}

class Cursor(object):
    def __init__(self, connection, dbname, collection):
        assert isinstance(connection, object)
        assert isinstance(dbname, (str, unicode))
        assert isinstance(collection, (str, unicode))
        
        self._connection = connection
        self.__dbname = dbname
        self.__collection = collection
    
    @property
    def full_collection_name(self):
        return '%s.%s' % (self.__dbname, self.__collection)
    
    def find_one(self, spec_or_id, **kwargs):
        """Get a single document from the database.

        All arguments to :meth:`find` are also valid arguments for
        :meth:`find_one`, although any `limit` argument will be
        ignored. Returns a single document, or ``None`` if no matching
        document is found.
        """
        if spec_or_id is not None and not isinstance(spec_or_id, dict):
            spec_or_id = {"_id": spec_or_id}
        kwargs['limit'] = -1
        self.find(spec_or_id, **kwargs)
    
    def find(self, spec=None, fields=None, skip=0, limit=0,
                 timeout=True, snapshot=False, tailable=False, sort=None,
                 max_scan=None, 
                 _must_use_master=False, _is_command=False, 
                 callback=None):
        """Query the database.
        
        The `spec` argument is a prototype document that all results
        must match. For example:
        
        >>> db.test.find({"hello": "world"}, callback=...)
        
        only matches documents that have a key "hello" with value
        "world".  Matches can have other keys *in addition* to
        "hello". The `fields` argument is used to specify a subset of
        fields that should be included in the result documents. By
        limiting results to a certain subset of fields you can cut
        down on network traffic and decoding time.
        
        Raises :class:`TypeError` if any of the arguments are of
        improper type. 
        
        :Parameters:
          - `spec` (optional): a SON object specifying elements which
            must be present for a document to be included in the
            result set
          - `fields` (optional): a list of field names that should be
            returned in the result set ("_id" will always be
            included), or a dict specifying the fields to return
          - `skip` (optional): the number of documents to omit (from
            the start of the result set) when returning the results
          - `limit` (optional): the maximum number of results to
            return
          - `timeout` (optional): if True, any returned cursor will be
            subject to the normal timeout behavior of the mongod
            process. Otherwise, the returned cursor will never timeout
            at the server. Care should be taken to ensure that cursors
            with timeout turned off are properly closed.
          - `snapshot` (optional): if True, snapshot mode will be used
            for this query. Snapshot mode assures no duplicates are
            returned, or objects missed, which were present at both
            the start and end of the query's execution. For details,
            see the `snapshot documentation
            <http://dochub.mongodb.org/core/snapshot>`_.
          - `tailable` (optional): the result of this find call will
            be a tailable cursor - tailable cursors aren't closed when
            the last data is retrieved but are kept open and the
            cursors location marks the final document's position. if
            more data is received iteration of the cursor will
            continue from the last document received. For details, see
            the `tailable cursor documentation
            <http://www.mongodb.org/display/DOCS/Tailable+Cursors>`_.
          - `sort` (optional): a list of (key, direction) pairs
            specifying the sort order for this query. See
            :meth:`~pymongo.cursor.Cursor.sort` for details.
          - `max_scan` (optional): limit the number of documents
            examined when performing the query
        
        .. mongodoc:: find
        """
         
        if spec is None:
            spec = {}

        if not isinstance(spec, dict):
            raise TypeError("spec must be an instance of dict")
        if not isinstance(skip, int):
            raise TypeError("skip must be an instance of int")
        if not isinstance(limit, int):
            raise TypeError("limit must be an instance of int")
        if not isinstance(timeout, bool):
            raise TypeError("timeout must be an instance of bool")
        if not isinstance(snapshot, bool):
            raise TypeError("snapshot must be an instance of bool")
        if not isinstance(tailable, bool):
            raise TypeError("tailable must be an instance of bool")
        if not callable(callback):
            raise TypeError("callback must be callable")
        
        if fields is not None:
            if not fields:
                fields = {"_id": 1}
            if not isinstance(fields, dict):
                fields = helpers._fields_list_to_dict(fields)
        
        self.__spec = spec
        self.__fields = fields
        self.__skip = skip
        self.__limit = limit
        self.__batch_size = 0
        
        self.__timeout = timeout
        self.__tailable = tailable
        self.__snapshot = snapshot
        self.__ordering = sort and helpers._index_document(sort) or None
        self.__max_scan = max_scan
        self.__explain = False
        self.__hint = None
        # self.__as_class = as_class
        self.__tz_aware = False #collection.database.connection.tz_aware
        self.__must_use_master = _must_use_master
        self.__is_command = False # _is_commandf
        
        self.callback = callback
        self.__id = self._connection.send_message(
            message.query(self.__query_options(),
                          self.full_collection_name,
                          self.__skip, self.__limit,
                          self.__query_spec(), self.__fields), callback=self._handle_response)
    
    def _handle_response(self, result):
        logging.info('%r' % result)
        # {'cursor_id': 0, 'data': [], 'number_returned': 0, 'starting_from': 0}
        self.callback(result['data'])
        self.callback = None
        # TODO: handle get_more; iteration of data
        # if self.__more_data:
        #     self._connection.send_message(
        #         message.get_more(self.full_collection_name,
        #                                self.__limit, self.__id), callback=self._handle_response)
        #     self.__more_data = None
        # else:
        #     self._callback(result)
    
    def __query_options(self):
        """Get the query options string to use for this query.
        """
        options = 0
        if self.__tailable:
            options |= _QUERY_OPTIONS["tailable_cursor"]
        if False: #self.__collection.database.connection.slave_okay:
            options |= _QUERY_OPTIONS["slave_okay"]
        if not self.__timeout:
            options |= _QUERY_OPTIONS["no_timeout"]
        return options
    
    def __query_spec(self):
        """Get the spec to use for a query.
        """
        spec = self.__spec
        if not self.__is_command and "$query" not in self.__spec:
            spec = SON({"$query": self.__spec})
        if self.__ordering:
            spec["$orderby"] = self.__ordering
        if self.__explain:
            spec["$explain"] = True
        if self.__hint:
            spec["$hint"] = self.__hint
        if self.__snapshot:
            spec["$snapshot"] = True
        if self.__max_scan:
            spec["$maxScan"] = self.__max_scan
        return spec
    
    