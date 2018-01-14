Awesome Public Datasets
=======================
.. image:: https://cdn.rawgit.com/sindresorhus/awesome/d7305f38d29fed78fa85652e3a63e154dd8e8829/media/badge.svg
   :alt: Awesome
   :target: https://github.com/sindresorhus/awesome

`This list of a topic-centric public data sources <https://github.com/caesar0301/awesome-public-datasets>`_ in high quality. They
are collected and tidied from blogs, answers, and user responses.
Most of the data sets listed below are free, however, some are not.
Other amazingly awesome lists can be found in the
`awesome-awesomeness <https://github.com/bayandin/awesome-awesomeness>`_ and
`sindresorhus's awesome <https://github.com/sindresorhus/awesome>`_ list.

.. contents:: Table of Contents


<%
    rows = [[v for v in range(0,10)] for row in range(0,10)]
%>
<table>
    % for row in rows:
        ${makerow(row)}
    % endfor
</table>

<%def name="makerow(row)">
    <tr>
    % for name in row:
        <td>${name}</td>\
    % endfor
    </tr>
</%def>


Complementary Collections
-------------------------

* `Data Packaged Core Datasets <https://github.com/datasets/>`_
* `Database of Scientific Code Contributions <https://mozillascience.org/collaborate>`_
* A growing collection of public datasets: `CoolDatasets. <http://cooldatasets.com/>`_
* DataWrangling: `Some Datasets Available on the Web <http://www.datawrangling.com/some-datasets-available-on-the-web>`_
* Inside-r: `Finding Data on the Internet <http://www.inside-r.org/howto/finding-data-internet>`_
* OpenDataMonitor: `An overview of available open data resources in Europe <http://opendatamonitor.eu>`_
* Quora: `Where can I find large datasets open to the public? <http://www.quora.com/Where-can-I-find-large-datasets-open-to-the-public>`_
* RS.io: `100+ Interesting Data Sets for Statistics <http://rs.io/100-interesting-data-sets-for-statistics/>`_
* StaTrek: `Leveraging open data to understand urban lives <http://xiaming.me/posts/2014/10/23/leveraging-open-data-to-understand-urban-lives/>`_