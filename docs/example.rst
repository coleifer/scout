.. _example:

Example
^^^^^^^

For example, let's consider the search indexes for a personal blog. We might have one index to store every entry, and a separate index to store comments.

Each blog entry would correspond to a document in the blog entry index. These documents could have associated metadata containing the ID of the entry, the entry's title and URL for easy link generation, and a boolean value to indicate whether the entry had been published.

If you frequently use images on your blog, you might also include the primary image for each blog entry as an attachment. That way when you are displaying search results, you could display the image if it existed.

The comment metadata would store the ID of the entry, to allow filtering by entry, as well as a boolean value indicating whether the comment was spam.

As another example, let's consider a news website. The news site would have indexes for things like articles, local events, sports scores, etc. To allow search over the entire site, you could add a "master" index in addition to the other indexes, that would store every kind of content.
