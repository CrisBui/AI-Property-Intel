package com.propertyintel.service.impl;

import com.propertyintel.dto.request.SearchRequest;
import com.propertyintel.dto.response.ListingCardResponse;
import com.propertyintel.dto.response.ListingDetailResponse;
import com.propertyintel.entity.Listing;
import com.propertyintel.mapper.ListingMapper;
import com.propertyintel.repository.ListingRepository;
import com.propertyintel.repository.spec.ListingSpecification;
import com.propertyintel.service.ListingService;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class ListingServiceImpl implements ListingService {
    private final ListingRepository listingRepository;
    private final ListingMapper listingMapper;

    @Override
    public Page<ListingCardResponse> searchListings(SearchRequest request) {
        Sort sort = Sort.by(Sort.Direction.ASC, "priceVnd");
        if (request.getSort().equalsIgnoreCase("price_desc")) {
            sort = Sort.by(Sort.Direction.DESC, "priceVnd");
        }
        int pageIndex = Math.max(0, request.getPage() - 1);
        PageRequest pageRequest = PageRequest.of(pageIndex, request.getSize(), sort);
        Specification<Listing> spec = ListingSpecification.filterByRequest(request);
        Page<Listing> listingPage = listingRepository.findAll(spec, pageRequest);
        return listingPage.map(listingMapper::toCardResponse);
    }

    @Override
    public ListingDetailResponse getListingDetail(String sourceId) {
        Listing listing = listingRepository.findBySourceId(sourceId)
                .orElseThrow(() -> new RuntimeException("Không tìm thấy phòng trọ!"));
        return listingMapper.toDetailResponse(listing);
    }

}
